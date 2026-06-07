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
from datetime import datetime, timezone

import structlog
import trafilatura
from langchain_core.documents import Document
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


# ─── Website loader ────────────────────────────────────────────────────────────

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

    # Tier 1: simple static page
    docs = await _load_web_base([url], base_meta)
    if docs and len(docs[0].page_content) >= 200:
        return _enrich(docs, base_meta)

    # Tier 2: archive / recursive crawl
    docs = await _load_recursive(url, base_meta)
    if docs:
        return _enrich(docs, base_meta)

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
    from langchain_community.document_loaders import PDFPlumberLoader
    try:
        return PDFPlumberLoader(url).load()
    except Exception as e:
        logger.warning("PDFPlumberLoader failed", url=url, error=str(e))
        return []


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
    last_checked_yyyymmdd = (
        last_checked.strftime("%Y%m%d") if last_checked else "19700101"
    )

    # On the very first sync, cap at 20 most-recent videos to avoid fetching
    # the entire channel history. Subsequent syncs rely on the date filter.
    is_first_sync = last_checked is None
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "ignoreerrors": True,
        **({"playlistend": 20} if is_first_sync else {}),
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
        # extract_flat=True often omits upload_date — treat missing date as
        # "include this video" so we don't silently skip everything.
        if not upload_date or upload_date >= last_checked_yyyymmdd:
            vid_id = entry.get("id") or entry.get("url", "")
            if vid_id:
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
            docs.append(Document(
                page_content=transcript_text,
                metadata={
                    "source": video_url,
                    "content_type": "video",
                    "investor_id": investor_id,
                    "source_id": source_id,
                    "transcript_available": True,
                },
            ))
        else:
            # Fallback: use title + description from yt-dlp metadata
            title_desc = _get_video_metadata(video_url)
            if title_desc:
                docs.append(Document(
                    page_content=title_desc,
                    metadata={
                        "source": video_url,
                        "content_type": "video",
                        "investor_id": investor_id,
                        "source_id": source_id,
                        "transcript_available": False,
                    },
                ))
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
