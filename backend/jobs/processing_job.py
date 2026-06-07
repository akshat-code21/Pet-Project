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
            "report_triggered": _should_trigger_report(item.content_type),
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


async def trigger_report_generation(investor_id: str, user_id: str) -> dict:
    """
    On-demand: generate a report for an investor from their most recent
    completed content items (called from POST /investors/{id}/report).
    """
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from models.investor import Investor
    from sqlalchemy import select, desc
    from agents.pipeline import run_pipeline
    from agents.state import PipelineState

    async with AsyncSessionLocal() as db:
        investor = (
            await db.execute(select(Investor).where(Investor.id == uuid.UUID(investor_id)))
        ).scalar_one_or_none()
        recent_items = (
            await db.execute(
                select(ContentItem)
                .where(
                    ContentItem.investor_id == uuid.UUID(investor_id),
                    ContentItem.processing_status == "completed",
                )
                .order_by(desc(ContentItem.created_at))
                .limit(5)
            )
        ).scalars().all()

    if not recent_items:
        return {"error": "No processed content available for report generation"}

    # Use the most recent item as the trigger
    item = recent_items[0]
    source_url = (item.extra_metadata or {}).get("source_url", "")

    initial_state: PipelineState = {
        "content_item_id": str(item.id),
        "investor_id": investor_id,
        "user_id": user_id,
        "content_type": item.content_type,
        "raw_text": item.raw_text or "",
        "source_url": source_url,
        "cleaned_text": item.cleaned_text or item.raw_text or "",
        "chunks": [],
        "entities": [],
        "theses": [],
        "embeddings_stored": False,
        "report_generated": False,
        "report_triggered": True,
        "alerts_created": [],
        "error": None,
        "investor_name": investor.name if investor else investor_id,
        "filing_period": "",
    }

    final_state = run_pipeline(initial_state)
    if final_state.get("error"):
        return {"error": final_state["error"]}
    return {"report_generated": final_state.get("report_generated", False)}
