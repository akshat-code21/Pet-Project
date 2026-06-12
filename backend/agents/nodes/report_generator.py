"""
Report generator node.
Triggered for: investor letters, newsletters, videos, and 13F filings.
Produces structured markdown using GPT-4o.

Also exposes generate_report_from_context() for on-demand consolidated
report generation (called from trigger_report_generation).
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


# ---------------------------------------------------------------------------
# Reusable report generation — used by both the pipeline node and
# the on-demand consolidated report path.
# ---------------------------------------------------------------------------

def generate_report_from_context(
    *,
    investor_id: str,
    user_id: str,
    investor_name: str,
    entities: list[dict],
    theses: list[dict],
    source_urls: list[str],
    content_item_ids: list[str],
    period_days: int = 30,
    filing_period: str = "N/A",
    portfolio_changes_json: str = "None",
) -> str:
    """Generate an investor report from pre-aggregated context.

    Returns the report markdown. Also persists the Report row to the DB.
    Raises on failure.
    """
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)

    now = datetime.now(timezone.utc)
    period_start = (now - timedelta(days=period_days)).strftime("%Y-%m-%d")
    period_end = now.strftime("%Y-%m-%d")

    source_links = "\n".join(f"- [{url}]({url})" for url in source_urls if url) or "- None"

    prompt = INVESTOR_REPORT_PROMPT.format(
        investor_name=investor_name,
        period_start=period_start,
        period_end=period_end,
        source_count=len(set(source_urls)),
        content_count=len(content_item_ids),
        entities_json=json.dumps(entities, indent=2)[:8000],
        theses_json=json.dumps(theses, indent=2)[:8000],
        portfolio_changes_json=portfolio_changes_json,
        previous_summary="No previous report.",
        generated_at=now.isoformat(),
        filing_period=filing_period,
        source_links=source_links,
    )

    markdown = _call_llm(client, prompt)
    markdown = clean_markdown_fences(markdown)

    # Persist report to DB
    _save_report_sync(
        investor_id=investor_id,
        user_id=user_id,
        markdown=markdown,
        period_start=period_start,
        period_end=period_end,
        content_item_ids=content_item_ids,
    )

    return markdown


# ---------------------------------------------------------------------------
# Pipeline node — delegates to generate_report_from_context
# ---------------------------------------------------------------------------

def report_generator_node(state: PipelineState) -> PipelineState:
    if not state.get("report_triggered"):
        return {**state, "report_generated": False}
    if state.get("content_type") not in REPORT_TRIGGER_TYPES:
        return {**state, "report_generated": False}

    try:
        generate_report_from_context(
            investor_id=state["investor_id"],
            user_id=state["user_id"],
            investor_name=state.get("investor_name", state["investor_id"]),
            entities=state.get("entities", []),
            theses=state.get("theses", []),
            source_urls=[state.get("source_url", "")],
            content_item_ids=[state["content_item_id"]],
            filing_period=state.get("filing_period", "N/A"),
            portfolio_changes_json="None",
        )
    except Exception as e:
        logger.error("Report generation failed", error=str(e))
        return {**state, "report_generated": False, "error": str(e)}

    return {**state, "report_generated": True}


# ---------------------------------------------------------------------------
# LLM call with retry
# ---------------------------------------------------------------------------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=60))
def _call_llm(client: OpenAI, prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
        timeout=90,
    )
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def _save_report_sync(
    investor_id: str,
    user_id: str,
    markdown: str,
    period_start: str,
    period_end: str,
    content_item_ids: list[str],
) -> None:
    """Fire-and-forget DB save via asyncio."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_save_report_async(investor_id, user_id, markdown, period_start, period_end, content_item_ids))
    except RuntimeError:
        pass  # No event loop in test context


async def _save_report_async(
    investor_id: str,
    user_id: str,
    markdown: str,
    period_start: str,
    period_end: str,
    content_item_ids: list[str],
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
            source_item_ids=[uuid.UUID(cid) for cid in content_item_ids],
            period_start=datetime.fromisoformat(period_start),
            period_end=datetime.fromisoformat(period_end),
        )
        db.add(report)
        await db.commit()
        logger.info("Report saved", investor_id=investor_id, content_items=len(content_item_ids))

