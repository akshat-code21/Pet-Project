import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_id: uuid.UUID
    investor_id: uuid.UUID
    content_type: str
    title: str | None
    url: str | None
    published_at: datetime | None
    processing_status: str
    processing_error: str | None
    extra_metadata: dict
    created_at: datetime


class PortfolioChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    investor_id: uuid.UUID
    ticker_symbol: str
    company_name: str | None
    cusip: str | None
    change_type: str
    shares_previous: int
    shares_current: int
    value_usd: int | None
    percent_of_portfolio: float | None
    filing_period: str
    report_date: datetime | None
    created_at: datetime
