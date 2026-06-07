"""
Report generator node.
Triggered for: investor letters, newsletters, videos, and 13F filings.
Produces structured markdown using GPT-4o.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.prompts.report_generation import INVESTOR_REPORT_PROMPT
from agents.state import PipelineState
from app.config import get_settings

logger = structlog.get_logger()

REPORT_TRIGGER_TYPES = {"filing", "article", "newsletter", "video"}


def clean_markdown_fences(content: str) -> str:
    cleaned = content.strip()
    if cleaned.startswith("```markdown"):
        cleaned = cleaned[11:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned.strip()


def report_generator_node(state: PipelineState) -> PipelineState:
    if not state.get("report_triggered"):
        return {**state, "report_generated": False}
    if state.get("content_type") not in REPORT_TRIGGER_TYPES:
        return {**state, "report_generated": False}

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    investor_id = state["investor_id"]
    user_id = state["user_id"]
    entities = state.get("entities", [])
    theses = state.get("theses", [])

    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    # Build portfolio changes summary from metadata if filing
    portfolio_changes_json = "None"
    filing_period = "N/A"
    if state.get("content_type") == "filing":
        # Holdings come through state metadata from the ingestion layer
        filing_period = state.get("filing_period", "N/A")

    source_links = f"- [{state.get('source_url', '')}]({state.get('source_url', '')})"

    try:
        prompt = INVESTOR_REPORT_PROMPT.format(
            investor_name=state.get("investor_name", investor_id),
            period_start=period_start,
            period_end=period_end,
            source_count=1,
            content_count=1,
            entities_json=json.dumps(entities, indent=2)[:4000],
            theses_json=json.dumps(theses, indent=2)[:4000],
            portfolio_changes_json=portfolio_changes_json,
            previous_summary="No previous report.",
            generated_at=now.isoformat(),
            filing_period=filing_period,
            source_links=source_links,
        )
        markdown = _generate_report(client, prompt)
        markdown = clean_markdown_fences(markdown)
    except Exception as e:
        logger.error("Report generation failed", error=str(e))
        return {**state, "report_generated": False, "error": str(e)}

    # Persist report to DB asynchronously
    _save_report_sync(
        investor_id=investor_id,
        user_id=user_id,
        markdown=markdown,
        period_start=period_start,
        period_end=period_end,
        content_item_id=state["content_item_id"],
    )

    return {**state, "report_generated": True}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=60))
def _generate_report(client: OpenAI, prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
        timeout=90,
    )
    return response.choices[0].message.content or ""


def _save_report_sync(
    investor_id: str,
    user_id: str,
    markdown: str,
    period_start: str,
    period_end: str,
    content_item_id: str,
) -> None:
    """Fire-and-forget DB save via asyncio."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_save_report_async(investor_id, user_id, markdown, period_start, period_end, content_item_id))
    except RuntimeError:
        pass  # No event loop in test context


async def _save_report_async(
    investor_id: str,
    user_id: str,
    markdown: str,
    period_start: str,
    period_end: str,
    content_item_id: str,
) -> None:
    from database.connection import AsyncSessionLocal
    from models.report import Report

    title_line = next((line for line in markdown.splitlines() if line.startswith("# ")), "Intelligence Report")
    title = title_line.lstrip("# ").strip()
    
    # Extract actual summary lines by ignoring metadata headers and hr tags
    summary_lines = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("---"):
            continue
        if line.startswith("**Generated:**") or line.startswith("**Period:**") or line.startswith("**Sources analyzed:**"):
            continue
        if line.startswith("```"):
            continue
        summary_lines.append(line)
        
    summary = " ".join(summary_lines[:3])[:300] if summary_lines else ""

    async with AsyncSessionLocal() as db:
        report = Report(
            user_id=uuid.UUID(user_id),
            investor_id=uuid.UUID(investor_id),
            report_type="investor_report",
            title=title,
            summary=summary,
            content_markdown=markdown,
            source_item_ids=[uuid.UUID(content_item_id)],
            period_start=datetime.fromisoformat(period_start),
            period_end=datetime.fromisoformat(period_end),
        )
        db.add(report)
        await db.commit()
        logger.info("Report saved", investor_id=investor_id)

