import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import services.investor_service as svc
from api.deps import get_current_user, get_session
from models.user import User
from schemas.investor import InvestorCreate, InvestorDetailResponse, InvestorResponse, InvestorUpdate

router = APIRouter()


@router.get("", response_model=list[InvestorResponse])
async def list_investors(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await svc.list_investors(db, current_user.id)


@router.post("", response_model=InvestorResponse, status_code=status.HTTP_201_CREATED)
async def create_investor(
    body: InvestorCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    return await svc.create_investor(db, current_user.id, body)


@router.get("/{investor_id}", response_model=InvestorDetailResponse)
async def get_investor(
    investor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    investor = await svc.get_investor(db, investor_id, current_user.id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    stats = await svc.get_investor_stats(db, investor_id)
    investor.sources_count = len(investor.sources)
    return InvestorDetailResponse.model_validate({**investor.__dict__, "stats": stats})


@router.put("/{investor_id}", response_model=InvestorResponse)
async def update_investor(
    investor_id: uuid.UUID,
    body: InvestorUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    investor = await svc.update_investor(db, investor_id, current_user.id, body)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")
    return investor


@router.delete("/{investor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investor(
    investor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    deleted = await svc.delete_investor(db, investor_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Investor not found")


@router.post("/{investor_id}/sync")
async def sync_investor(
    investor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    investor = await svc.get_investor(db, investor_id, current_user.id)
    if not investor:
        raise HTTPException(status_code=404, detail="Investor not found")

    from jobs.ingestion_job import run_ingestion_for_investor
    # Await directly so the response tells you what was ingested (or what failed).
    # The scheduler uses fire-and-forget; the API endpoint is synchronous so you
    # can see results immediately.
    result = await run_ingestion_for_investor(investor_id)
    return {"message": "sync complete", **result}
