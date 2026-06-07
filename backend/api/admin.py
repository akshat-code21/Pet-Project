from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_current_user, get_session
from models.content_item import ContentItem
from models.user import User

router = APIRouter()

@router.get("/jobs/status")
async def job_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    pending = (await db.execute(
        select(func.count()).select_from(ContentItem).where(ContentItem.processing_status == "pending")
    )).scalar_one()

    try:
        from jobs.scheduler import get_scheduler
        scheduler = get_scheduler()
        jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
        running = scheduler.running
    except Exception:
        jobs, running = [], False

    return {"data": {"scheduler_running": running, "jobs": jobs, "pending_content_items": pending}}

@router.post("/jobs/trigger")
async def trigger_job(
    body: dict,
    current_user: User = Depends(get_current_user),
):
    """Immediately run a scheduled job and return its result."""
    job_name = body.get("job", "")

    JOB_MAP = {
        "process_pending": "jobs.processing_job.process_pending_content",
        "ingest_rss": "jobs.ingestion_job.run_ingestion_for_source_type",
        "ingest_websites": "jobs.ingestion_job.run_ingestion_for_source_type",
        "ingest_youtube": "jobs.ingestion_job.run_ingestion_for_source_type",
        "ingest_sec_13f": "jobs.ingestion_job.run_ingestion_for_source_type",
        "daily_digest": "jobs.digest_job.run_daily_digest",
    }

    if job_name not in JOB_MAP:
        return {"error": f"Unknown job '{job_name}'. Valid jobs: {list(JOB_MAP)}"}

    try:
        module_path, func_name = JOB_MAP[job_name].rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        fn = getattr(mod, func_name)

        # Pass source_type argument for ingestion jobs
        source_type_map = {
            "ingest_rss": "rss",
            "ingest_websites": "website",
            "ingest_youtube": "youtube",
            "ingest_sec_13f": "sec_13f",
        }
        if job_name in source_type_map:
            result = await fn(source_type_map[job_name])
        else:
            result = await fn()

        return {"message": f"job '{job_name}' complete", "result": result}
    except Exception as e:
        return {"error": str(e)}
