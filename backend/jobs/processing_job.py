"""
Processing job.
Picks up pending ContentItem records and runs them through the LangGraph pipeline.
Also exposes trigger_report_generation() for on-demand report requests from the API.
"""
import uuid
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()

BATCH_SIZE = 10  # max items to process per scheduler tick


async def process_pending_content(batch_size: int = BATCH_SIZE) -> dict:
    """
    Scheduled job: find pending ContentItems and run the pipeline on each.
    Marks items as processing before the run, then completed/failed after.
    """
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from models.investor import Investor
    from models.source import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ContentItem)
                .where(ContentItem.processing_status == "pending")
                .order_by(ContentItem.created_at.asc())
                .limit(batch_size)
            )
        ).scalars().all()

        if not rows:
            logger.debug("process_pending_content: nothing to process")
            return {"processed": 0, "failed": 0}

        # Mark all as processing to prevent double-processing in concurrent runs
        for item in rows:
            item.processing_status = "processing"
        await db.commit()

    results = {"processed": 0, "failed": 0}

    for item in rows:
        success = await _run_pipeline_for_item(item)
        if success:
            results["processed"] += 1
        else:
            results["failed"] += 1

    logger.info("Processing batch complete", **results)
    return results


async def _run_pipeline_for_item(item) -> bool:
    """Run a single ContentItem through the LangGraph pipeline."""
    from database.connection import AsyncSessionLocal
    from models.investor import Investor
    from models.source import Source
    from models.user import User
    from sqlalchemy import select
    from agents.pipeline import run_pipeline
    from agents.state import PipelineState

    content_item_id = str(item.id)
    investor_id = str(item.investor_id)
    source_id = str(item.source_id)

    try:
        # Fetch associated investor and user for pipeline state
        async with AsyncSessionLocal() as db:
            investor = (
                await db.execute(select(Investor).where(Investor.id == item.investor_id))
            ).scalar_one_or_none()
            user = (
                await db.execute(select(User).where(User.id == investor.user_id))
            ).scalar_one_or_none() if investor else None

        if not investor or not user:
            logger.warning("Missing investor or user for content item", content_item_id=content_item_id)
            await _mark_failed(content_item_id, "investor or user not found")
            return False

        source_url = (item.extra_metadata or {}).get("source_url", "")
        filing_period = (item.extra_metadata or {}).get("filing_period", "")

        initial_state: PipelineState = {
            "content_item_id": content_item_id,
            "investor_id": investor_id,
            "user_id": str(investor.user_id),
            "content_type": item.content_type,
            "raw_text": item.raw_text or "",
            "source_url": source_url,
            "cleaned_text": "",
            "chunks": [],
            "entities": [],
            "theses": [],
            "embeddings_stored": False,
            "report_generated": False,
            "report_triggered": False,  # Reports are only generated on-demand via /reports/generate
            "alerts_created": [],
            "error": None,
            # Extra context for report generator
            "investor_name": investor.name,
            "filing_period": filing_period,
        }

        final_state = run_pipeline(initial_state)

        if final_state.get("error"):
            await _mark_failed(content_item_id, final_state["error"])
            return False

        await _mark_completed(content_item_id, final_state)
        return True

    except Exception as e:
        logger.error("Pipeline execution error", content_item_id=content_item_id, error=str(e))
        await _mark_failed(content_item_id, str(e))
        return False


def _should_trigger_report(content_type: str) -> bool:
    """Determine if a new report should be generated for this content."""
    return content_type in {"filing", "article", "newsletter", "video"}


async def _mark_completed(content_item_id: str, final_state: dict) -> None:
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        item = (
            await db.execute(select(ContentItem).where(ContentItem.id == uuid.UUID(content_item_id)))
        ).scalar_one_or_none()
        if item:
            item.processing_status = "completed"
            item.cleaned_text = final_state.get("cleaned_text", "")
            item.extracted_entities = final_state.get("entities", [])
            item.extracted_theses = final_state.get("theses", [])
            await db.commit()


async def _mark_failed(content_item_id: str, error: str) -> None:
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        item = (
            await db.execute(select(ContentItem).where(ContentItem.id == uuid.UUID(content_item_id)))
        ).scalar_one_or_none()
        if item:
            item.processing_status = "failed"
            item.extra_metadata = {**(item.extra_metadata or {}), "error": error}
            await db.commit()

def _deduplicate_entities(all_entities: list[dict]) -> list[dict]:
    """Merge entities across multiple content items, keeping highest conviction."""
    conviction_rank = {"high": 3, "medium": 2, "low": 1, "unknown": 0, None: 0}
    seen: dict[str, dict] = {}  # key -> entity

    for entity in all_entities:
        key = f"{entity.get('entity_type', '')}/{(entity.get('entity_name') or '').lower()}"
        existing = seen.get(key)
        if existing is None:
            seen[key] = entity
        else:
            # Keep the one with higher conviction
            if conviction_rank.get(entity.get("conviction_level"), 0) > conviction_rank.get(existing.get("conviction_level"), 0):
                seen[key] = entity

    return list(seen.values())


def _deduplicate_theses(all_theses: list[dict]) -> list[dict]:
    """Merge theses across multiple content items, keeping highest conviction score."""
    seen: dict[str, dict] = {}  # key -> thesis

    for thesis in all_theses:
        key = (thesis.get("company") or "").lower()
        ticker = (thesis.get("ticker") or "").upper()
        if ticker:
            key = ticker  # prefer ticker as key when available

        existing = seen.get(key)
        if existing is None:
            seen[key] = thesis
        else:
            # Keep the one with higher conviction score
            if (thesis.get("conviction_score") or 0) > (existing.get("conviction_score") or 0):
                seen[key] = thesis

    return list(seen.values())


async def trigger_report_generation(investor_id: str, user_id: str, period_days: int = 30) -> dict:
    """
    On-demand consolidated report generation.

    Aggregates ALL completed content items for the investor within the
    period_days window, merges their extracted entities and theses,
    and produces a single consolidated report.

    Called from POST /reports/generate.
    """
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from models.investor import Investor
    from sqlalchemy import select, desc
    from datetime import datetime, timedelta, timezone
    from agents.nodes.report_generator import generate_report_from_context

    investor_uuid = investor_id if isinstance(investor_id, uuid.UUID) else uuid.UUID(investor_id)
    user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)

    cutoff = datetime.now(timezone.utc) - timedelta(days=period_days)

    async with AsyncSessionLocal() as db:
        investor = (
            await db.execute(select(Investor).where(Investor.id == investor_uuid))
        ).scalar_one_or_none()
        recent_items = (
            await db.execute(
                select(ContentItem)
                .where(
                    ContentItem.investor_id == investor_uuid,
                    ContentItem.processing_status == "completed",
                    ContentItem.created_at >= cutoff,
                )
                .order_by(desc(ContentItem.created_at))
            )
        ).scalars().all()

    if not recent_items:
        return {"error": "No processed content available for report generation"}

    # Aggregate entities and theses across all content items
    all_entities: list[dict] = []
    all_theses: list[dict] = []
    source_urls: list[str] = []
    content_item_ids: list[str] = []

    for item in recent_items:
        content_item_ids.append(str(item.id))
        source_urls.append((item.extra_metadata or {}).get("source_url", ""))

        if item.extracted_entities:
            all_entities.extend(item.extracted_entities)
        if item.extracted_theses:
            all_theses.extend(item.extracted_theses)

    # Deduplicate across items
    merged_entities = _deduplicate_entities(all_entities)
    merged_theses = _deduplicate_theses(all_theses)

    investor_name = investor.name if investor else str(investor_uuid)

    logger.info(
        "Generating consolidated report",
        investor_id=str(investor_uuid),
        content_items=len(content_item_ids),
        entities=len(merged_entities),
        theses=len(merged_theses),
        period_days=period_days,
    )

    try:
        generate_report_from_context(
            investor_id=str(investor_uuid),
            user_id=str(user_uuid),
            investor_name=investor_name,
            entities=merged_entities,
            theses=merged_theses,
            source_urls=source_urls,
            content_item_ids=content_item_ids,
            period_days=period_days,
        )
    except Exception as e:
        logger.error("Consolidated report generation failed", error=str(e))
        return {"error": str(e)}

    return {"report_generated": True, "content_items_aggregated": len(content_item_ids)}
