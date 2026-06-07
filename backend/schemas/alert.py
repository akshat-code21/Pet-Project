import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    investor_id: uuid.UUID | None
    content_item_id: uuid.UUID | None
    report_id: uuid.UUID | None
    alert_type: str
    title: str
    summary: str | None
    severity: str
    score: int
    is_read: bool
    email_sent: bool
    metadata: dict
    created_at: datetime
    investor_name: str | None = None

    @model_validator(mode='before')
    @classmethod
    def map_extra_metadata(cls, obj: Any) -> Any:
        # When obj is an ORM instance, .metadata returns SQLAlchemy's MetaData()
        # not the JSONB column (which is mapped as extra_metadata).
        # Convert to a plain dict first so Pydantic doesn't hit that collision.
        if isinstance(obj, dict):
            return obj
        return {
            'id': obj.id,
            'user_id': obj.user_id,
            'investor_id': obj.investor_id,
            'content_item_id': obj.content_item_id,
            'report_id': getattr(obj, 'report_id', None),
            'alert_type': obj.alert_type,
            'title': obj.title,
            'summary': obj.summary,
            'severity': obj.severity,
            'score': obj.score,
            'is_read': obj.is_read,
            'email_sent': obj.email_sent,
            'metadata': obj.extra_metadata or {},   # ← the real JSONB column
            'created_at': obj.created_at,
            'investor_name': getattr(obj, 'investor_name', None),
        }


class AlertListResponse(BaseModel):
    data: list[AlertResponse]
    unread_count: int
    total: int
