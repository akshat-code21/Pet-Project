"""
Daily digest job.
Generates one consolidated digest report per user and emails it.
Runs at 07:00 UTC every day via APScheduler.
"""
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from agents.prompts.report_generation import DAILY_DIGEST_PROMPT
from app.config import get_settings

logger = structlog.get_logger()


async def generate_daily_digests() -> dict:
    """Scheduled job entry point — generates digests for all active users."""
    from database.connection import AsyncSessionLocal
    from models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User))).scalars().all()

    results = {"users": len(users), "sent": 0, "failed": 0, "skipped": 0}

    for user in users:
        try:
            sent = await _generate_digest_for_user(user)
            if sent:
                results["sent"] += 1
            else:
                results["skipped"] += 1
        except Exception as e:
            logger.error("Digest generation failed", user_id=str(user.id), error=str(e))
            results["failed"] += 1

    logger.info("Daily digest job complete", **results)
    return results


async def _generate_digest_for_user(user) -> bool:
    """Generate and email a digest for a single user. Returns True if email was sent."""
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from models.investor import Investor
    from models.report import Report
    from sqlalchemy import select, desc

    user_id = str(user.id)
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        # All investors for this user
        investors = (
            await db.execute(
                select(Investor).where(
                    Investor.user_id == user.id,
                    Investor.is_active.is_(True),
                )
            )
        ).scalars().all()

        if not investors:
            return False

        investor_ids = [inv.id for inv in investors]

        # New content items since last run
        new_items = (
            await db.execute(
                select(ContentItem)
                .where(
                    ContentItem.investor_id.in_(investor_ids),
                    ContentItem.processing_status == "completed",
                    ContentItem.created_at >= since,
                )
                .order_by(desc(ContentItem.created_at))
                .limit(50)
            )
        ).scalars().all()

    if not new_items:
        logger.info("No new content for digest", user_id=user_id)
        return False

    # Build context for the digest prompt
    investor_map = {str(inv.id): inv.name for inv in investors}
    content_summaries = []
    for item in new_items[:20]:  # cap at 20 for token budget
        name = investor_map.get(str(item.investor_id), "Unknown")
        snippet = (item.cleaned_text or item.raw_text or "")[:500]
        url = (item.extra_metadata or {}).get("source_url", "")
        content_summaries.append(f"[{name}] ({item.content_type}) {url}\n{snippet}")

    content_block = "\n\n---\n\n".join(content_summaries)
    investor_names = ", ".join(set(investor_map.values()))

    # Generate markdown via GPT-4o
    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        markdown = _call_digest_llm(
            client=client,
            investor_names=investor_names,
            date_str=now.strftime("%B %d, %Y"),
            content_block=content_block,
            item_count=len(new_items),
        )
        markdown = clean_markdown_fences(markdown)
    except Exception as e:
        logger.error("Digest LLM call failed", user_id=user_id, error=str(e))
        return False

    # Persist the digest report
    report_id = await _save_digest_report(
        user_id=user_id,
        markdown=markdown,
        period_start=(now - timedelta(days=1)).isoformat(),
        period_end=now.isoformat(),
        source_item_ids=[str(item.id) for item in new_items],
    )

    # Send email
    from services.email_service import send_digest_email
    await send_digest_email(
        user_email=user.email,
        user_name=user.full_name,
        report_markdown=markdown,
        report_id=report_id,
    )
    return True


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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=10, max=60))
def _call_digest_llm(
    client: OpenAI,
    investor_names: str,
    date_str: str,
    content_block: str,
    item_count: int,
) -> str:
    prompt = DAILY_DIGEST_PROMPT.format(
        investor_names=investor_names,
        date=date_str,
        content_count=item_count,
        content_summaries=content_block[:12000],  # token budget
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=3000,
        timeout=90,
    )
    return response.choices[0].message.content or ""


async def _save_digest_report(
    user_id: str,
    markdown: str,
    period_start: str,
    period_end: str,
    source_item_ids: list[str],
) -> str:
    from database.connection import AsyncSessionLocal
    from models.report import Report

    title_line = next((line for line in markdown.splitlines() if line.startswith("# ")), "Daily Digest")
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
        if line.startswith("**Date:**") or line.startswith("**Investors with activity:**") or line.startswith("Date:"):
            continue
        if line.startswith("```"):
            continue
        summary_lines.append(line)
        
    summary = " ".join(summary_lines[:3])[:300] if summary_lines else ""

    report = Report(
        user_id=uuid.UUID(user_id),
        investor_id=None,
        report_type="daily_digest",
        title=title,
        summary=summary,
        content_markdown=markdown,
        source_item_ids=[uuid.UUID(sid) for sid in source_item_ids],
        period_start=datetime.fromisoformat(period_start),
        period_end=datetime.fromisoformat(period_end),
    )

    async with AsyncSessionLocal() as db:
        db.add(report)
        await db.commit()
        await db.refresh(report)
        report_id = str(report.id)

    logger.info("Digest report saved", user_id=user_id, report_id=report_id)
    return report_id

