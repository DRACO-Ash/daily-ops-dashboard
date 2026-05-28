from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    udl_id: Optional[str] = None
    notice_id: Optional[str] = None
    msg_type: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_until: Optional[datetime] = None
    subject: Optional[str] = None
    description: Optional[str] = None
    sat_no: Optional[int] = None
    region: Optional[str] = None
    classification_marking: Optional[str] = None
    data_mode: Optional[str] = None
    source: Optional[str] = None
    udl_created_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class NotificationDetail(NotificationRead):
    raw: dict[str, Any]


class NotificationPage(BaseModel):
    items: list[NotificationRead]
    total: int
    limit: int
    offset: int


class NotificationIngestRequest(BaseModel):
    msg_type: Optional[str] = "TACREP_NOTSO"
    created_at_gte: Optional[datetime] = None
    data_mode: Optional[str] = None
    source: Optional[str] = None
    max_results: Optional[int] = None


class NotificationIngestResponse(BaseModel):
    pulled: int
    inserted: int
    updated: int
    skipped: int
