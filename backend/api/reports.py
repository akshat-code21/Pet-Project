import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_current_user, get_session
from models.user import User
from schemas.report import ReportDetailResponse, ReportGenerateRequest, ReportResponse
import services.report_service as svc

router = APIRouter()

@router.get("", response_model=dict)
async def list_reports(
    investor_id: uuid.UUID | None = Query(None),
    report_type: str | None = Query(None),
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    offset = (page - 1) * limit
    reports, total = await svc.list_reports(db, current_user.id, investor_id, report_type, unread_only, limit, offset)
    return {"data": [ReportResponse.model_validate(r) for r in reports], "total": total, "page": page}

@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    report = await svc.get_report(db, report_id, current_user.id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report

@router.patch("/{report_id}/read", response_model=ReportResponse)
async def mark_read(
    report_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    report = await svc.mark_report_read(db, report_id, current_user.id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report

@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    body: ReportGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    import asyncio
    asyncio.create_task(svc.generate_investor_report(body.investor_id, current_user.id))
    return {"message": "report generation queued", "job_id": str(body.investor_id)}
