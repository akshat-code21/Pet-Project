"""
SEC EDGAR 13F adapter.
Custom implementation — Kay.ai LangChain retriever requires paid key.
Uses EDGAR REST API directly (free, no key needed).
Rate limit: 10 req/s. Always send User-Agent header.
"""

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
import structlog
from bs4 import BeautifulSoup
from langchain_core.documents import Document
from tenacity import retry, stop_after_attempt, wait_exponential

from ingestion.base_adapter import BaseAdapter

logger = structlog.get_logger()

EDGAR_HEADERS = {
    "User-Agent": "HedgeFundIntelligence/1.0 (contact@hedgefundintelligence.com)",
    "Accept-Encoding": "gzip, deflate",
}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"

# Both possible 13F XML filenames
INFOTABLE_FILENAMES = ["infotable.xml", "informationtable.xml"]

# XML namespaces used across different 13F versions
NS_PATTERNS = [
    "{http://www.sec.gov/edgar/document/thirteenf/informationtable}",
    "{http://www.sec.gov/edgar/thirteenf/informationtable}",
    "{http://www.sec.gov/edgar/thirteenf}",
    "",  # no namespace fallback
]


class SECEdgarAdapter(BaseAdapter):
    async def fetch(self, source) -> list[Document]:
        cik = source.config.get("cik_number") or ""
        if not cik:
            logger.warning("SEC adapter: no cik_number in source config", source_id=str(source.id))
            return []

        cik_padded = cik.zfill(10)
        last_accession = source.config.get("last_accession", "")

        try:
            filings = await self._get_recent_13f_filings(cik_padded)
        except Exception as e:
            logger.error("EDGAR submissions fetch failed", cik=cik_padded, error=str(e))
            raise

        docs = []
        for filing in filings:
            accession = filing["accessionNumber"]
            if accession == last_accession:
                break

            filing_period = filing.get("reportDate", "")
            period_label = _period_label(filing_period)

            try:
                holdings = await self._parse_13f(
                    cik_padded,
                    accession,
                    primary_doc=filing.get("primaryDocument", ""),
                )
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning("13F parse failed", accession=accession, error=str(e))
                continue

            raw_xml_summary = _holdings_to_text(holdings, filing_period)
            doc = Document(
                page_content=raw_xml_summary,
                metadata={
                    "source": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik_padded}&type=13F-HR",
                    "content_type": "filing",
                    "investor_id": str(source.investor_id),
                    "source_id": str(source.id),
                    "accession_number": accession,
                    "filing_period": period_label,
                    "report_date": filing_period,
                    "published_at": filing.get("filingDate", ""),
                    "title": f"13F Filing — {period_label}",
                    "holdings": holdings,
                },
            )
            docs.append(doc)

        return docs

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=30))
    async def _get_recent_13f_filings(self, cik_padded: str) -> list[dict]:
        url = SUBMISSIONS_URL.format(cik=cik_padded)
        async with httpx.AsyncClient(headers=EDGAR_HEADERS, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        recent = data.get("filings", {}).get("recent", {})
        form_types = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        filing_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])

        primary_docs = recent.get("primaryDocument", [])

        return [
            {
                "accessionNumber": accessions[i].replace("-", ""),
                "filingDate": filing_dates[i],
                "reportDate": report_dates[i],
                "primaryDocument": primary_docs[i] if i < len(primary_docs) else "",
            }
            for i, ft in enumerate(form_types)
            if ft in ("13F-HR", "13F-HR/A")
        ]

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _parse_13f(
        self, cik_padded: str, accession_nodash: str, primary_doc: str = ""
    ) -> list[dict]:
        cik = cik_padded.lstrip("0")
        base_url = ARCHIVES_BASE.format(cik=cik, accession=accession_nodash)

        async with httpx.AsyncClient(
            headers=EDGAR_HEADERS, follow_redirects=True, timeout=60
        ) as client:
            xml_content = await self._fetch_infotable_xml(
                client, cik, accession_nodash, primary_doc, base_url
            )

        if not xml_content:
            raise ValueError(f"Could not fetch infotable XML for accession {accession_nodash}")

        if xml_content.strip().startswith(("<!DOCTYPE html", "<html")):
            return _parse_html_holdings(xml_content)

        return _parse_infotable_xml(xml_content)

    async def _fetch_infotable_xml(
        self,
        client: httpx.AsyncClient,
        cik: str,
        accession_nodash: str,
        primary_doc: str,
        base_url: str,
    ) -> str | None:
        """Try multiple strategies to find and fetch the 13F information table XML."""

        # Strategy 1: old infotable.xml / informationtable.xml
        for fname in INFOTABLE_FILENAMES:
            try:
                resp = await client.get(base_url + fname)
                if resp.status_code == 200:
                    return resp.text
                await asyncio.sleep(0.1)
            except Exception:
                continue

        # Strategy 2: filing index JSON
        try:
            xml_content = await self._fetch_infotable_from_index_json(
                client, base_url, accession_nodash
            )
            if xml_content:
                return xml_content
        except Exception:
            pass

        # Strategy 3: filing index HTM (expanded search)
        try:
            xml_content = await self._fetch_infotable_from_index_htm(
                client, base_url, accession_nodash
            )
            if xml_content:
                return xml_content
        except Exception:
            pass

        # Strategy 4: root primary_doc.xml (without XSLT subdirectory prefix)
        if primary_doc:
            try:
                xml_content = await self._fetch_root_primary_doc(
                    client, cik, accession_nodash, primary_doc
                )
                if xml_content:
                    return xml_content
            except Exception:
                pass

        return None

    async def _fetch_infotable_from_index_json(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        accession_nodash: str,
    ) -> str | None:
        """Find info table XML via filing index.json.

        Heuristic 1: item with type 'INFORMATION TABLE'
        Heuristic 2 (Berkshire fallback): first .xml that isn't primary_doc
        """
        index_url = f"{base_url}{accession_nodash}-index.json"
        resp = await client.get(index_url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("directory", {}).get("item", [])
        if not items:
            return None

        filename = _find_infotable_filename(items)
        if not filename:
            return None
        await asyncio.sleep(0.1)
        xml_resp = await client.get(base_url + filename)
        if xml_resp.status_code == 200:
            return xml_resp.text
        return None

    async def _fetch_infotable_from_index_htm(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        accession_nodash: str,
    ) -> str | None:
        """Find info table XML via filing index.htm."""
        idx_resp = await client.get(base_url + f"{accession_nodash}-index.htm")
        if idx_resp.status_code != 200:
            return None

        # Try regex match for known infotable patterns
        xml_url = _find_infotable_url(idx_resp.text, base_url)
        if xml_url:
            await asyncio.sleep(0.1)
            xml_resp = await client.get(xml_url)
            if xml_resp.status_code == 200:
                return xml_resp.text

        # Expanded fallback: scan all .xml links in the table, try the
        # first one that isn't primary_doc or XBRL
        soup = BeautifulSoup(idx_resp.text, "html.parser")
        for link in soup.find_all("a"):
            href = str(link.get("href", ""))
            if (
                href.endswith(".xml")
                and "primary_doc" not in href
                and not href.endswith("_htm.xml")
            ):
                full_url = href if href.startswith("http") else f"https://www.sec.gov{href}"
                await asyncio.sleep(0.1)
                xml_resp = await client.get(full_url)
                if xml_resp.status_code == 200:
                    text = xml_resp.text
                    if "infotable" in text.lower() or "nameOfIssuer" in text:
                        return text
        return None

    async def _fetch_root_primary_doc(
        self,
        client: httpx.AsyncClient,
        cik: str,
        accession_nodash: str,
        primary_doc: str,
    ) -> str | None:
        """Fetch primary_doc.xml from the filing ROOT (strip XSLT subdir).

        The raw XML at root contains both cover-page AND info-table data,
        while the XSLT-subdirectory URL returns HTML (server-side XSLT).
        """
        xml_filename = primary_doc.rsplit("/", 1)[-1] if "/" in primary_doc else primary_doc
        if not xml_filename.endswith(".xml"):
            return None
        root_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/{xml_filename}"
        )
        resp = await client.get(root_url)
        if resp.status_code == 200:
            return resp.text
        return None


def _parse_infotable_xml(xml_content: str) -> list[dict]:
    """Parse 13F infotable XML into list of holding dicts. Handles multiple namespace patterns."""
    root = ET.fromstring(xml_content)
    holdings = []

    for ns in NS_PATTERNS:
        info_tables = root.findall(f".//{ns}infoTable")
        if not info_tables:
            info_tables = root.findall(f".//{ns}InfoTable")
        if info_tables:
            for table in info_tables:

                def g(tag):
                    for n in NS_PATTERNS:
                        el = table.find(f"{n}{tag}")
                        if el is None:
                            el = table.find(f"{n}{tag[0].upper() + tag[1:]}")
                        if el is not None and el.text:
                            return el.text.strip()
                    return ""

                shares_el = table.find(f"{ns}shrsOrPrnAmt")
                if shares_el is None:
                    shares_el = table.find(f"{ns}ShrsorPrnAmt")
                shares = 0
                if shares_el is not None:
                    for n in NS_PATTERNS:
                        s = shares_el.find(f"{n}sshPrnamt") or shares_el.find(f"{n}SshPrnamt")
                        if s is not None and s.text:
                            try:
                                shares = int(s.text.strip())
                            except ValueError:
                                pass
                            break

                holdings.append(
                    {
                        "name": g("nameOfIssuer"),
                        "cusip": g("cusip"),
                        "value": _safe_int(g("value")),
                        "shares": shares,
                        "put_call": g("putCall"),
                    }
                )
            break

    return holdings


def _parse_html_holdings(html_content: str) -> list[dict]:
    """Parse 13F holdings from the XSLT-transformed HTML cover page.

    Modern SEC 13F filings embed the information table within HTML.
    This extracts holding data (name, CUSIP, value, shares) from the HTML tables.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    holdings = []

    # The information table is typically the table with the most rows
    # that contains "Name of Issuer" or similar header text
    tables = soup.find_all("table")
    data_table = None

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue
        header_text = " ".join(
            cell.get_text(strip=True).lower() for cell in rows[0].find_all(["th", "td"])
        )
        if "name of issuer" in header_text or "issuer" in header_text:
            data_table = table
            break

    if data_table is None:
        # Fallback: pick the table with the most rows (skip cover-page tables)
        candidate = None
        max_rows = 0
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) > max_rows:
                max_rows = len(rows)
                candidate = table
        if candidate and max_rows >= 3:
            data_table = candidate

    if data_table is None:
        return holdings

    rows = data_table.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        cell_texts = [cell.get_text(strip=True) for cell in cells]

        name = cell_texts[0]
        if not name or name.lower() in ("", "name of issuer", "issuer"):
            continue

        cusip = cell_texts[1] if len(cell_texts) > 1 else ""
        value_str = cell_texts[2] if len(cell_texts) > 2 else ""
        shares_str = cell_texts[3] if len(cell_texts) > 3 else ""

        holdings.append(
            {
                "name": name,
                "cusip": cusip.upper() if cusip else "",
                "value": _safe_int(value_str.replace("$", "").replace(",", "")),
                "shares": _safe_int(shares_str.replace(",", "")),
                "put_call": "",
            }
        )

    return holdings


def _holdings_to_text(holdings: list[dict], period: str) -> str:
    lines = [f"13F Holdings — Period: {period}", f"Total positions: {len(holdings)}", ""]
    for h in holdings:
        lines.append(
            f"{h['name']} | CUSIP:{h['cusip']} | Value:${h['value']}K | Shares:{h['shares']}"
        )
    return "\n".join(lines)


def _period_label(report_date: str) -> str:
    """Convert '2024-09-30' → '2024-Q3'."""
    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    except ValueError:
        return report_date


def _find_infotable_filename(items: list[dict]) -> str | None:
    """Find info table XML filename from SEC filing index.json items.

    Heuristic 1: item with type 'INFORMATION TABLE'
    Heuristic 2: first .xml that isn't primary_doc or XBRL instance doc
    """
    for item in items:
        if item.get("type", "").upper() == "INFORMATION TABLE":
            name = item.get("name", "")
            if name.endswith(".xml"):
                return name
    for item in items:
        name = item.get("name", "")
        if name.endswith(".xml") and "primary_doc" not in name and not name.endswith("_htm.xml"):
            return name
    return None


def _find_infotable_url(index_html: str, base_url: str) -> str | None:
    """Scan index HTML for infotable link."""
    for pattern in [
        r'href="([^"]*infotable[^"]*\.xml)"',
        r'href="([^"]*informationtable[^"]*\.xml)"',
    ]:
        m = re.search(pattern, index_html, re.IGNORECASE)
        if m:
            path = m.group(1)
            return path if path.startswith("http") else f"https://www.sec.gov{path}"
    return None


def _safe_int(val: str) -> int:
    try:
        return int(val.replace(",", ""))
    except (ValueError, AttributeError):
        return 0
