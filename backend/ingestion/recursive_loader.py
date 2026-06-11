"""
Generic recursive link-following loader.

Problem this solves
--------------------
Some pages contain *no* substantive content themselves — they are just an
index/landing page of hyperlinks, and the useful data lives one (or more)
clicks deeper. The clearest example is an SEC EDGAR "Filing Detail" page
(``...-index.htm``): the page body is a table of links to ``primary_doc.html``,
``infotable.xml`` etc., and the holdings only exist inside those child files.

A plain article extractor (trafilatura) returns almost nothing for such a page,
and a naive crawler would either miss the structured tables or wander off into
the whole site. This loader does a *bounded* breadth-first crawl:

  * starts at one URL,
  * follows in-page links up to ``max_depth`` (default 2),
  * stays on the same registered domain by default,
  * caps total fetches at ``max_pages`` so it can never run away,
  * de-duplicates with a visited set,
  * dispatches each fetched URL to the right parser by content type
    (13F XML, generic XML tables, HTML article/tables, PDF, plain text),
  * reuses the battle-tested 13F parsers in ``sec_adapter`` so SEC holdings
    come back fully structured.

It returns ``list[Document]`` like every other loader, so it slots straight
into the existing ingestion pipeline.
"""

from __future__ import annotations

import asyncio
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx
import structlog
import trafilatura
from bs4 import BeautifulSoup
from langchain_core.documents import Document

from ingestion.sec_adapter import (
    EDGAR_HEADERS,
    _holdings_to_text,
    _parse_html_holdings,
    _parse_infotable_xml,
)

logger = structlog.get_logger()

DEFAULT_HEADERS = EDGAR_HEADERS  # polite UA; SEC requires one, harmless elsewhere

# A page is treated as an "index" (worth following its links) when it has lots
# of links but little real text.
INDEX_MIN_LINKS = 5
INDEX_MAX_TEXT_CHARS = 400

# Extensions we never want to enqueue as crawl targets.
_SKIP_EXT = (
    ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
    ".woff", ".woff2", ".ttf", ".zip", ".mp4", ".mov", ".webp",
)


# ─── Public entry point ────────────────────────────────────────────────────────


async def load_recursive_links(
    start_url: str,
    base_meta: dict | None = None,
    *,
    max_depth: int = 2,
    max_pages: int = 40,
    same_domain: bool = True,
    headers: dict | None = None,
    request_delay: float = 0.2,
) -> list[Document]:
    """Recursively follow links from ``start_url`` and capture content from each.

    Parameters
    ----------
    start_url      The page to begin from (typically an index/detail page).
    base_meta      Metadata merged into every returned Document.
    max_depth      How many link-hops to follow (0 = only the start page).
    max_pages      Hard cap on total fetches (safety brake).
    same_domain    Only follow links on the same registered domain.
    headers        Override request headers (defaults to a polite SEC UA).
    request_delay  Seconds to sleep between requests (rate-limit courtesy).
    """
    base_meta = dict(base_meta or {})
    headers = headers or DEFAULT_HEADERS
    start_domain = _registered_domain(start_url)

    visited: set[str] = set()
    documents: list[Document] = []
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])

    async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=60) as client:
        while queue and len(visited) < max_pages:
            url, depth = queue.popleft()
            url = _strip_fragment(url)
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
            except Exception as e:  # noqa: BLE001
                logger.warning("recursive_loader: fetch failed", url=url, error=str(e))
                continue
            if resp.status_code != 200:
                logger.debug("recursive_loader: non-200", url=url, status=resp.status_code)
                continue

            content_type = resp.headers.get("content-type", "").lower()
            body = resp.text

            doc, child_links = await _handle_response(
                client, url, depth, body, content_type, base_meta
            )
            if doc is not None:
                documents.append(doc)

            # Decide whether to descend further.
            if depth < max_depth and child_links:
                for link in child_links:
                    if same_domain and _registered_domain(link) != start_domain:
                        continue
                    link = _strip_fragment(link)
                    if link not in visited and not _should_skip(link):
                        queue.append((link, depth + 1))

            await asyncio.sleep(request_delay)

    logger.info(
        "recursive_loader: done",
        start=start_url,
        fetched=len(visited),
        documents=len(documents),
    )
    return _enrich(documents, base_meta)


# ─── Per-response dispatch ──────────────────────────────────────────────────────


async def _handle_response(
    client: httpx.AsyncClient,
    url: str,
    depth: int,
    body: str,
    content_type: str,
    base_meta: dict,
) -> tuple[Document | None, list[str]]:
    """Return (Document or None, child_links_to_follow)."""
    lower_url = url.lower()
    stripped = body.lstrip()[:200].lower()
    is_xml = "xml" in content_type or lower_url.endswith(".xml") or stripped.startswith("<?xml")
    is_html = "html" in content_type or stripped.startswith(("<!doctype html", "<html"))

    # 1) XML — could be a 13F information table or generic structured data.
    if is_xml and not is_html:
        doc = _document_from_xml(url, body, base_meta)
        return doc, []  # XML leaves have no links to follow

    # 2) PDF — delegate to the existing PDF loader in loaders.py.
    if lower_url.endswith(".pdf") or "application/pdf" in content_type:
        from ingestion.loaders import _load_pdf

        pdf_docs = await _load_pdf(url, base_meta)
        return (pdf_docs[0] if pdf_docs else None), []

    # 3) HTML — extract links + any text/tables.
    if is_html:
        soup = BeautifulSoup(body, "html.parser")
        child_links = _extract_links(soup, url)
        text = (trafilatura.extract(body) or "").strip()
        table_text = _tables_to_text(soup)

        index_like = len(child_links) >= INDEX_MIN_LINKS and len(text) < INDEX_MAX_TEXT_CHARS

        # On an SEC filing-index page, prioritise the data files so they get
        # fetched first even if max_pages is small.
        child_links = _prioritise_data_links(child_links)

        captured = "\n\n".join(t for t in (text, table_text) if t).strip()
        doc = None
        if captured and not index_like:
            doc = Document(
                page_content=captured,
                metadata={
                    "source": url,
                    "content_type": base_meta.get("content_type", "website_page"),
                    "depth": depth,
                },
            )
        return doc, child_links

    # 4) Plain text (e.g. EDGAR complete-submission .txt).
    if body.strip():
        doc = Document(
            page_content=body.strip()[:200_000],
            metadata={"source": url, "content_type": "text", "depth": depth},
        )
        return doc, []

    return None, []


# ─── XML handling ───────────────────────────────────────────────────────────────


def _document_from_xml(url: str, xml_content: str, base_meta: dict) -> Document | None:
    """Turn an XML file into a Document. Uses the 13F parser when it looks like
    an information table, otherwise falls back to a generic XML→text dump."""
    looks_like_13f = "infotable" in xml_content.lower() or "nameofissuer" in xml_content.lower()

    if looks_like_13f:
        try:
            holdings = _parse_infotable_xml(xml_content)
        except Exception as e:  # noqa: BLE001
            logger.warning("recursive_loader: infotable parse failed", url=url, error=str(e))
            holdings = []
        if holdings:
            return Document(
                page_content=_holdings_to_text(holdings, base_meta.get("filing_period", "")),
                metadata={
                    "source": url,
                    "content_type": "filing",
                    "holdings": holdings,
                    "parsed_as": "13f_infotable",
                },
            )

    # Generic structured XML: try HTML-table heuristics, else flatten the text.
    if "<table" in xml_content.lower():
        holdings = _parse_html_holdings(xml_content)
        if holdings:
            return Document(
                page_content=_holdings_to_text(holdings, base_meta.get("filing_period", "")),
                metadata={"source": url, "content_type": "filing", "holdings": holdings},
            )

    text = _xml_to_text(xml_content)
    if text.strip():
        return Document(
            page_content=text,
            metadata={"source": url, "content_type": "structured_xml"},
        )
    return None


def _xml_to_text(xml_content: str) -> str:
    """Flatten an arbitrary XML document into ``tag: value`` lines."""
    soup = BeautifulSoup(xml_content, "xml")
    lines: list[str] = []
    for el in soup.find_all(True):
        # Only leaf elements with text.
        if not el.find(True) and el.get_text(strip=True):
            lines.append(f"{el.name}: {el.get_text(strip=True)}")
    return "\n".join(lines)[:200_000]


# ─── HTML helpers ───────────────────────────────────────────────────────────────


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        href = str(a.get("href", "")).strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        if full not in seen:
            seen.add(full)
            links.append(full)
    return links


def _prioritise_data_links(links: list[str]) -> list[str]:
    """Push likely data files (.xml, .pdf, .txt, infotable, primary_doc) to the front."""

    def score(u: str) -> int:
        lu = u.lower()
        if "infotable" in lu or "informationtable" in lu:
            return 0
        if lu.endswith(".xml") or lu.endswith(".pdf"):
            return 1
        if "primary_doc" in lu:
            return 2
        if lu.endswith(".txt"):
            return 3
        return 5

    return sorted(links, key=score)


def _tables_to_text(soup: BeautifulSoup) -> str:
    """Serialise HTML <table>s into pipe-delimited text so tabular data is kept."""
    out: list[str] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        for row in rows:
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if any(cells):
                out.append(" | ".join(cells))
        out.append("")
    return "\n".join(out).strip()


# ─── small utilities ────────────────────────────────────────────────────────────


def _registered_domain(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    parts = netloc.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def _should_skip(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(_SKIP_EXT)


def _enrich(docs: list[Document], base_meta: dict) -> list[Document]:
    for doc in docs:
        for k, v in base_meta.items():
            doc.metadata.setdefault(k, v)
    return docs


# ─── standalone CLI runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    async def _main() -> None:
        if len(sys.argv) < 2:
            print("usage: python -m ingestion.recursive_loader <url> [max_depth] [max_pages]")
            raise SystemExit(1)
        url = sys.argv[1]
        depth = int(sys.argv[2]) if len(sys.argv) > 2 else 2
        pages = int(sys.argv[3]) if len(sys.argv) > 3 else 40
        docs = await load_recursive_links(url, max_depth=depth, max_pages=pages)
        print(f"\n=== {len(docs)} document(s) captured from {url} ===\n")
        for i, d in enumerate(docs, 1):
            holdings = d.metadata.get("holdings")
            print(f"[{i}] {d.metadata.get('source')}")
            print(f"    content_type={d.metadata.get('content_type')} "
                  f"parsed_as={d.metadata.get('parsed_as', '-')}")
            if holdings:
                print(f"    holdings parsed: {len(holdings)}")
                print("    sample:", json.dumps(holdings[:3], indent=2)[:600])
            else:
                print(f"    text preview: {d.page_content[:160]!r}")
            print()

    asyncio.run(_main())
