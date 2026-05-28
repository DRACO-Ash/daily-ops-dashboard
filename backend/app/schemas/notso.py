from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotsoRead(BaseModel):
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


class NotsoDetail(NotsoRead):
    raw: dict[str, Any]


class NotsoPage(BaseModel):
    items: list[NotsoRead]
    total: int
    limit: int
    offset: int


class NotsoIngestRequest(BaseModel):
    effective_from_gte: Optional[datetime] = None
    msg_type: Optional[str] = None
    max_results: Optional[int] = None


class NotsoIngestResponse(BaseModel):
    pulled: int
    inserted: int
    updated: int
    skipped: int
