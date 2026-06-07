"""
Ingestion jobs.
Fetches raw content from all active sources and stores ContentItem records.
Called by APScheduler (run_ingestion_for_source_type) and by the
POST /investors/{id}/sync API endpoint (run_ingestion_for_investor).
"""

import hashlib
import uuid
from datetime import datetime, timezone

import structlog

logger = structlog.get_logger()


async def run_ingestion_for_investor(investor_id) -> dict:
    """Trigger ingestion for ALL active sources belonging to one investor.

    Accepts investor_id as either a str or uuid.UUID.
    """
    from database.connection import AsyncSessionLocal
    from models.source import Source
    from sqlalchemy import select

    # Normalize: accept both str and uuid.UUID
    investor_uuid = (
        investor_id if isinstance(investor_id, uuid.UUID) else uuid.UUID(str(investor_id))
    )

    async with AsyncSessionLocal() as db:
        sources = (
            (
                await db.execute(
                    select(Source).where(
                        Source.investor_id == investor_uuid, Source.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    results = {"investor_id": str(investor_uuid), "processed": 0, "failed": 0, "skipped": 0}
    for source in sources:
        r = await _ingest_source(source)
        results["processed"] += r.get("new_items", 0)
        results["failed"] += 1 if r.get("error") else 0
        results["skipped"] += r.get("skipped", 0)

    logger.info("Investor ingestion complete", **results)
    return results


async def run_ingestion_for_source_type(source_type: str) -> dict:
    """Scheduled job: ingest all active sources of a given source_type."""
    from database.connection import AsyncSessionLocal
    from models.source import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        sources = (
            (
                await db.execute(
                    select(Source).where(
                        Source.source_type == source_type, Source.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )

    results = {"source_type": source_type, "sources": len(sources), "processed": 0, "failed": 0}
    for source in sources:
        r = await _ingest_source(source)
        results["processed"] += r.get("new_items", 0)
        results["failed"] += 1 if r.get("error") else 0

    logger.info("Source-type ingestion complete", **results)
    return results


async def _ingest_source(source) -> dict:
    """Fetch documents from a single source and persist new ContentItem records."""
    from database.connection import AsyncSessionLocal
    from models.content_item import ContentItem
    from sqlalchemy import select
    from ingestion.content_hasher import compute_hash

    source_type = source.source_type
    source_id = str(source.id)
    investor_id = str(source.investor_id)

    log = logger.bind(source_id=source_id, source_type=source_type)

    # Inject CIK from investor into source config if missing for SEC
    if source_type == "sec_13f" and not source.config.get("cik_number"):
        async with AsyncSessionLocal() as db:
            from models.investor import Investor
            from sqlalchemy import select

            investor = (
                await db.execute(select(Investor).where(Investor.id == uuid.UUID(investor_id)))
            ).scalar_one_or_none()
            if investor and investor.cik_number:
                source.config["cik_number"] = investor.cik_number

    try:
        docs = await _fetch_documents(source)
    except Exception as e:
        log.error("Fetch failed", error=str(e))
        await _increment_failure(source_id)
        return {"error": str(e)}

    if not docs:
        log.info("No new documents")
        return {"new_items": 0, "skipped": 0}

    new_count = 0
    skip_count = 0
    seen_hashes: set[str] = set()  # track duplicates within this batch

    async with AsyncSessionLocal() as db:
        for doc in docs:
            raw_text = doc.page_content or ""

            # ── Sanitise text for PostgreSQL ─────────────────────────────
            # 1. Skip binary / non-text content — check BEFORE stripping null
            #    bytes so that null bytes (strongest binary indicator) are
            #    detected as non-printable characters.
            sample = raw_text[:1000]
            if sample:
                non_printable = sum(
                    1 for c in sample if not c.isprintable() and c not in ("\n", "\r", "\t")
                )
                if non_printable / len(sample) > 0.15:
                    log.debug("Skipping binary/garbled document", source_id=source_id)
                    skip_count += 1
                    continue

            # 2. Strip null bytes (PG rejects \x00 in text columns)
            raw_text = raw_text.replace("\x00", "")

            if not raw_text.strip():
                skip_count += 1
                continue

            content_hash = compute_hash(raw_text)

            # Duplicate check — within this batch AND in the DB
            if content_hash in seen_hashes:
                skip_count += 1
                continue
            existing = (
                await db.execute(
                    select(ContentItem.id).where(ContentItem.content_hash == content_hash)
                )
            ).scalar_one_or_none()
            if existing:
                skip_count += 1
                continue
            seen_hashes.add(content_hash)

            content_type = _detect_content_type(source_type, doc.metadata)

            # Sanitise metadata values – strip null bytes from all string values
            safe_metadata = {}
            for k, v in doc.metadata.items():
                if k in ("source", "title", "published"):
                    continue
                if isinstance(v, str):
                    safe_metadata[k] = v.replace("\x00", "")
                else:
                    safe_metadata[k] = v

            item = ContentItem(
                source_id=uuid.UUID(source_id),
                investor_id=uuid.UUID(investor_id),
                content_type=content_type,
                raw_text=raw_text,
                content_hash=content_hash,
                processing_status="pending",
                extra_metadata={
                    "source_url": (doc.metadata.get("source", source.url) or "").replace(
                        "\x00", ""
                    ),
                    "title": (doc.metadata.get("title", "") or "").replace("\x00", ""),
                    "published_at": (doc.metadata.get("published", "") or "").replace("\x00", ""),
                    **safe_metadata,
                },
            )
            db.add(item)
            new_count += 1

        await db.commit()

    # Reset failure counter on success
    await _reset_failure(source_id)
    await _update_last_checked(source_id)

    log.info("Ingestion done", new_items=new_count, skipped=skip_count)
    return {"new_items": new_count, "skipped": skip_count}


async def _fetch_documents(source) -> list:
    """Dispatch to the correct adapter/loader."""
    source_type = source.source_type

    if source_type == "sec_13f":
        from ingestion.sec_adapter import SECEdgarAdapter

        adapter = SECEdgarAdapter()
        return await adapter.fetch(source)
    elif source_type in ("website", "custom"):
        from ingestion.loaders import load_website

        return await load_website(source)
    elif source_type == "rss":
        from ingestion.loaders import load_rss

        return await load_rss(source)
    elif source_type == "youtube":
        from ingestion.loaders import load_youtube

        return await load_youtube(source)
    else:
        logger.warning("Unknown source_type, skipping", source_type=source_type)
        return []


def _detect_content_type(source_type: str, metadata: dict) -> str:
    if source_type == "sec_13f":
        return "filing"
    if source_type == "youtube":
        return "video"
    if source_type == "rss":
        return "article"
    # Website heuristics
    url = metadata.get("source", "").lower()
    if url.endswith(".pdf"):
        return "filing"
    return "article"


async def _increment_failure(source_id: str) -> None:
    from database.connection import AsyncSessionLocal
    from models.source import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        source = (
            await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
        ).scalar_one_or_none()
        if source:
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            if source.consecutive_failures >= 5:
                source.is_active = False
                logger.warning("Source disabled after 5 consecutive failures", source_id=source_id)
            await db.commit()


async def _reset_failure(source_id: str) -> None:
    from database.connection import AsyncSessionLocal
    from models.source import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        source = (
            await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
        ).scalar_one_or_none()
        if source and source.consecutive_failures:
            source.consecutive_failures = 0
            await db.commit()


async def _update_last_checked(source_id: str) -> None:
    from database.connection import AsyncSessionLocal
    from models.source import Source
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        source = (
            await db.execute(select(Source).where(Source.id == uuid.UUID(source_id)))
        ).scalar_one_or_none()
        if source:
            source.last_checked_at = datetime.now(timezone.utc)
            await db.commit()
