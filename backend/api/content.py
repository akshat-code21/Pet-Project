import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.deps import get_current_user, get_session
from models.user import User
from schemas.content import ContentItemResponse, PortfolioChangeResponse
import services.content_service as svc
import services.investor_service as inv_svc

router = APIRouter()

@router.get("", response_model=list[ContentItemResponse])
async def list_content(
    investor_id: uuid.UUID = Query(...),
    content_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    investor = await inv_svc.get_investor(db, investor_id, current_user.id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    return await svc.list_content_items(db, investor_id, content_type, limit, offset)

@router.get("/portfolio-changes", response_model=list[PortfolioChangeResponse])
async def get_portfolio(
    investor_id: uuid.UUID = Query(...),
    filing_period: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    investor = await inv_svc.get_investor(db, investor_id, current_user.id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    return await svc.get_portfolio_changes(db, investor_id, filing_period)
