import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReportType = Literal["investor_report", "daily_digest", "event_report"]


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    investor_id: uuid.UUID | None
    report_type: str
    title: str
    summary: str | None
    is_read: bool
    period_start: datetime | None
    period_end: datetime | None
    generated_at: datetime
    created_at: datetime
    investor_name: str | None = None


class ReportDetailResponse(ReportResponse):
    content_markdown: str
    source_item_ids: list[uuid.UUID]


class ReportGenerateRequest(BaseModel):
    investor_id: uuid.UUID
    report_type: ReportType = "investor_report"
    period_days: int = 30
