from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_key: str
    narrative: str
    source_notification_ids: list[str]
    latest_notification_id: Optional[UUID] = None
    publication_count: int
    model: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
