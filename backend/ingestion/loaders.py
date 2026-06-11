"""
LangChain-powered content loaders.
All functions return List[Document] with standardised metadata.

Tier selection for websites:
  1. WebBaseLoader         — simple static pages
  2. RecursiveUrlLoader    — archive / multi-page sites (depth=2)
  3. AsyncChromiumLoader   — JS-heavy SPAs (fallback when tier 1 returns <200 chars)
  4. PDFPlumberLoader      — .pdf URLs
  5. SitemapLoader         — when source.config["has_sitemap"] = True
"""

import asyncio
import re
from datetime import datetime, timezone

import structlog
import trafilatura
from langchain_core.documents import Document
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()

# YouTube video IDs are always exactly 11 characters: [A-Za-z0-9_-]
# This naturally rejects channel IDs (24 chars, start with "UC") and
# any other malformed IDs returned by yt-dlp for unavailable videos.
YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


# ─── Website loader ────────────────────────────────────────────────────────────


def _is_binary_content(text: str) -> bool:
    """Return True if text looks like binary garbage (PDF bytes, images, etc.)."""
    if not text:
        return True
    sample = text[:500]
    non_printable = sum(1 for c in sample if not c.isprintable() and c not in ("\n", "\r", "\t"))
    return non_printable / max(len(sample), 1) > 0.15


async def load_website(source) -> list[Document]:
    url: str = source.url
    investor_id = str(source.investor_id)
    source_id = str(source.id)
    base_meta = {"investor_id": investor_id, "source_id": source_id, "content_type": "website_page"}

    # Tier 5: sitemap
    if source.config.get("has_sitemap"):
        sitemap_url = source.config.get("sitemap_url", url.rstrip("/") + "/sitemap.xml")
        return await _load_sitemap(sitemap_url, base_meta)

    # Tier 4: PDF
    if url.lower().endswith(".pdf"):
        return await _load_pdf(url, base_meta)

    # Tier 1: simple static page — but first detect index/listing pages.
    # Some pages (e.g. report listing with monthly PDF links) pass the old
    # ≥200-char threshold because nav-bar text + link labels add up, yet
    # contain no substantive article content.  We fetch the raw HTML once
    # and run a smarter heuristic: if the page has many hyperlinks but
    # very little extracted article text it is an index page, and we should
    # fall through to the recursive link-following tier.
    is_index_page = False
    data_links = 0
    raw_html: str | None = None
    try:
        import httpx
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                raw_html = resp.text
    except Exception as e:
        logger.debug("Pre-fetch for index detection failed", url=url, error=str(e))

    if raw_html:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")

        # Count meaningful outbound links and data-file links (.pdf, .xml, etc.)
        _DATA_EXT = (".pdf", ".xml", ".csv", ".xlsx", ".xls", ".doc", ".docx")
        total_links = 0
        data_links = 0
        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            total_links += 1
            if href.lower().split("?", 1)[0].endswith(_DATA_EXT):
                data_links += 1

        # Use trafilatura for article-quality text extraction (ignores nav/boilerplate)
        article_text = (trafilatura.extract(raw_html) or "").strip()

        # Heuristic 1: page is predominantly a file index (many data-file links)
        # e.g. Pershing Square reports page: 420 PDFs out of 448 total links
        if data_links >= 5:
            is_index_page = True
            logger.info(
                "Detected data-file index page — will follow links",
                url=url, total_links=total_links, data_links=data_links,
            )
        # Heuristic 2: many links but very little article text per link
        # (pages whose "article text" is just disclaimers/boilerplate)
        elif total_links >= 10 and (len(article_text) / max(total_links, 1)) < 50:
            is_index_page = True
            logger.info(
                "Detected link-heavy index page — will follow links",
                url=url, total_links=total_links, article_chars=len(article_text),
                chars_per_link=len(article_text) / max(total_links, 1),
            )

    if not is_index_page:
        docs = await _load_web_base([url], base_meta)
        if docs and len(docs[0].page_content) >= 200:
            return _enrich(docs, base_meta)

    # Tier 1.5: index-style page (mostly hyperlinks, little text).
    # The real data likely lives in linked child pages (e.g. an SEC filing-
    # index that links to infotable.xml, or a report listing with PDF links).
    # Follow those links recursively and capture the structured data.
    if source.config.get("follow_links", True):
        from ingestion.recursive_loader import load_recursive_links

        # When we detected a data-file-heavy index, auto-scale max_pages so
        # we actually fetch all the linked documents, and limit depth to 1
        # (no need to crawl further from individual PDFs/XMLs).
        cfg_max_pages = source.config.get("max_pages")
        cfg_max_depth = source.config.get("max_depth")
        if is_index_page and data_links > 0:
            effective_max_pages = int(cfg_max_pages) if cfg_max_pages else min(data_links + 10, 500)
            effective_max_depth = int(cfg_max_depth) if cfg_max_depth else 1
        else:
            effective_max_pages = int(cfg_max_pages) if cfg_max_pages else 40
            effective_max_depth = int(cfg_max_depth) if cfg_max_depth else 2

        link_docs = await load_recursive_links(
            url,
            base_meta,
            max_depth=effective_max_depth,
            max_pages=effective_max_pages,
            same_domain=bool(source.config.get("same_domain", True)),
        )
        if link_docs:
            return _enrich(link_docs, base_meta)

    # Tier 2: archive / recursive crawl
    docs = await _load_recursive(url, base_meta)
    if docs:
        # Post-process: detect PDF links and binary content from recursive crawl
        clean_docs = []
        for doc in docs:
            doc_url = doc.metadata.get("source", "") or ""
            # If URL ends in .pdf, re-fetch with PDF loader
            if doc_url.lower().endswith(".pdf"):
                pdf_docs = await _load_pdf(doc_url, base_meta)
                clean_docs.extend(pdf_docs)
            elif _is_binary_content(doc.page_content):
                # Binary content from non-PDF URL — skip it
                logger.debug("Skipping binary document from recursive crawl", url=doc_url)
                continue
            else:
                clean_docs.append(doc)
        return _enrich(clean_docs, base_meta)

    # Tier 3: JS-heavy fallback
    docs = await _load_chromium([url], base_meta)
    return _enrich(docs, base_meta)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=30))
async def _load_web_base(urls: list[str], base_meta: dict) -> list[Document]:
    from langchain_community.document_loaders import WebBaseLoader

    try:
        loader = WebBaseLoader(urls)
        return loader.load()
    except Exception as e:
        logger.warning("WebBaseLoader failed", urls=urls, error=str(e))
        return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=5, max=20))
async def _load_recursive(url: str, base_meta: dict) -> list[Document]:
    from langchain_community.document_loaders.recursive_url_loader import RecursiveUrlLoader

    try:
        loader = RecursiveUrlLoader(
            url,
            max_depth=2,
            extractor=lambda html: trafilatura.extract(html) or "",
        )
        return loader.load()
    except Exception as e:
        logger.warning("RecursiveUrlLoader failed", url=url, error=str(e))
        return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=5, max=20))
async def _load_chromium(urls: list[str], base_meta: dict) -> list[Document]:
    from langchain_community.document_loaders import AsyncChromiumLoader
    from langchain_community.document_transformers import Html2TextTransformer

    try:
        raw = AsyncChromiumLoader(urls).load()
        return Html2TextTransformer().transform_documents(raw)
    except Exception as e:
        logger.warning("AsyncChromiumLoader failed", urls=urls, error=str(e))
        return []


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=5, max=20))
async def _load_pdf(url: str, base_meta: dict) -> list[Document]:
    """Download a remote PDF to a temp file and parse with PDFPlumberLoader."""
    import tempfile
    import httpx
    from langchain_community.document_loaders import PDFPlumberLoader

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        docs = PDFPlumberLoader(tmp_path).load()
        # Attach the original URL as the source
        for doc in docs:
            doc.metadata["source"] = url
        return docs
    except Exception as e:
        logger.warning("PDF load failed", url=url, error=str(e))
        return []
    finally:
        import os

        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=5, max=20))
async def _load_sitemap(sitemap_url: str, base_meta: dict) -> list[Document]:
    from langchain_community.document_loaders.sitemap import SitemapLoader

    try:
        return SitemapLoader(sitemap_url).load()
    except Exception as e:
        logger.warning("SitemapLoader failed", url=sitemap_url, error=str(e))
        return []


# ─── RSS loader ────────────────────────────────────────────────────────────────


async def load_rss(source) -> list[Document]:
    """
    Uses RSSFeedLoader (feedparser + newspaper3k full article body).
    Filters to entries published after source.last_checked_at.
    """
    from langchain_community.document_loaders import RSSFeedLoader

    base_meta = {
        "investor_id": str(source.investor_id),
        "source_id": str(source.id),
        "content_type": "newsletter",
    }
    last_checked = source.last_checked_at

    try:
        loader = RSSFeedLoader(urls=[source.url])
        all_docs = loader.load()
    except Exception as e:
        logger.error("RSSFeedLoader failed", url=source.url, error=str(e))
        return []

    new_docs = []
    for doc in all_docs:
        pub_date_str = doc.metadata.get("publish_date") or doc.metadata.get("published")
        if last_checked and pub_date_str:
            try:
                pub_dt = datetime.fromisoformat(str(pub_date_str).replace("Z", "+00:00"))
                if pub_dt.replace(tzinfo=timezone.utc) <= last_checked.replace(tzinfo=timezone.utc):
                    continue
            except (ValueError, TypeError):
                pass
        doc.metadata.update(base_meta)
        new_docs.append(doc)

    return new_docs


# ─── YouTube loader ────────────────────────────────────────────────────────────


async def load_youtube(source) -> list[Document]:
    """
    Step 1: Discover new video URLs via yt-dlp (no API key needed).
    Step 2: Load transcripts via youtube-transcript-api directly (v0.x and v1.x compatible).
    """
    import yt_dlp

    channel_url: str = source.url
    investor_id = str(source.investor_id)
    source_id = str(source.id)

    last_checked = source.last_checked_at
    last_checked_yyyymmdd = last_checked.strftime("%Y%m%d") if last_checked else "19700101"

    # On the very first sync, cap at 20 most-recent videos to avoid fetching
    # the entire channel history. Subsequent syncs rely on the date filter.
    is_first_sync = last_checked is None
    ydl_opts = {
        "quiet": True,
        "ignoreerrors": True,
        "extract_flat": False,
        **({"playlistend": 20} if is_first_sync else {"playlistend": 50}),
    }

    # Step 1: enumerate new video URLs
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            entries = info.get("entries", []) if info else []
    except Exception as e:
        logger.error("yt-dlp channel listing failed", url=channel_url, error=str(e))
        return []

    video_urls = []
    for entry in entries:
        upload_date = entry.get("upload_date", "")
        vid_id = entry.get("id") or ""
        # Validate: YouTube video IDs are exactly 11 characters.
        # yt-dlp with extract_flat=True + ignoreerrors=True may return
        # entries where id is None (unavailable video) or malformed.
        if not vid_id or not YOUTUBE_VIDEO_ID_RE.match(vid_id):
            continue
        # extract_flat=True often omits upload_date — treat missing date as
        # "include this video" so we don't silently skip everything.
        if not upload_date or upload_date >= last_checked_yyyymmdd:
            video_urls.append(f"https://www.youtube.com/watch?v={vid_id}")

    logger.info("YouTube: found new videos", count=len(video_urls), channel=channel_url)

    # Step 2: fetch transcripts directly (bypasses LangChain's YoutubeLoader
    # which calls the removed list_transcripts() in youtube-transcript-api v1.x)
    docs = []
    for video_url in video_urls:
        await asyncio.sleep(1)  # courtesy rate limit
        transcript_text = await asyncio.get_event_loop().run_in_executor(
            None, _fetch_transcript, video_url
        )
        if transcript_text:
            vid_id = video_url.split("v=")[-1]
            docs.append(
                Document(
                    page_content=transcript_text,
                    metadata={
                        "source": video_url,
                        "content_type": "video",
                        "investor_id": investor_id,
                        "source_id": source_id,
                        "transcript_available": True,
                    },
                )
            )
        else:
            # Fallback: use title + description from yt-dlp metadata
            title_desc = _get_video_metadata(video_url)
            if title_desc:
                docs.append(
                    Document(
                        page_content=title_desc,
                        metadata={
                            "source": video_url,
                            "content_type": "video",
                            "investor_id": investor_id,
                            "source_id": source_id,
                            "transcript_available": False,
                        },
                    )
                )
            else:
                logger.warning("No transcript or metadata available, skipping", url=video_url)

    return docs


def _fetch_transcript(video_url: str) -> str:
    """
    Fetch YouTube transcript using youtube-transcript-api.
    Supports v1.x (instance-based) and v0.x (class-based) APIs.
    Returns empty string if no transcript is available.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    video_id = video_url.split("v=")[-1].split("&")[0]

    try:
        # v1.x: instantiate then call fetch(video_id)
        api = YouTubeTranscriptApi()
        snippets = api.fetch(video_id)
        return " ".join(s.text if hasattr(s, "text") else s.get("text", "") for s in snippets)
    except TypeError:
        pass
    except Exception as e:
        logger.debug("v1.x transcript fetch failed", video_id=video_id, error=str(e))

    try:
        # v0.x fallback: list_transcripts class method
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        snippets = transcript.fetch()
        return " ".join(s["text"] for s in snippets)
    except Exception as e:
        logger.debug("v0.x transcript fetch failed", video_id=video_id, error=str(e))

    return ""


def _get_video_metadata(video_url: str) -> str:
    """Fetch video title + description via yt-dlp for transcript fallback."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(video_url, download=False)
            title = info.get("title", "")
            desc = (info.get("description") or "")[:500]
            return f"{title}. {desc}".strip()
    except Exception:
        return video_url


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _enrich(docs: list[Document], base_meta: dict) -> list[Document]:
    """Merge base_meta into each doc's metadata without overwriting existing keys."""
    for doc in docs:
        for k, v in base_meta.items():
            doc.metadata.setdefault(k, v)
    return docs
