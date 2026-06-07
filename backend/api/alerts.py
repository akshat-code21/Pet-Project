import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_current_user, get_session
from models.user import User
from schemas.alert import AlertListResponse, AlertResponse
import services.alert_service as svc

router = APIRouter()

@router.get("", response_model=AlertListResponse, response_model_by_alias=True)
async def list_alerts(
    investor_id: uuid.UUID | None = Query(None),
    severity: str | None = Query(None),
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    offset = (page - 1) * limit
    alerts, total, unread_count = await svc.list_alerts(db, current_user.id, investor_id, severity, unread_only, limit, offset)
    return AlertListResponse(
        data=[AlertResponse.model_validate(a) for a in alerts],
        unread_count=unread_count,
        total=total,
    )

@router.patch("/{alert_id}/read", response_model=AlertResponse, response_model_by_alias=True)
async def mark_read(
    alert_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    alert = await svc.mark_alert_read(db, alert_id, current_user.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertResponse.model_validate(alert)

@router.patch("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    count = await svc.mark_all_read(db, current_user.id)
    return {"message": "all alerts marked as read", "count": count}
