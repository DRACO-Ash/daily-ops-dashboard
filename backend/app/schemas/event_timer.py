from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Recurrence = Literal["none", "daily", "weekly", "monthly"]


class EventTimerCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    target_time: datetime
    event_key: Optional[str] = Field(default=None, max_length=200)
    pre_alert_minutes: int = Field(default=5, ge=0, le=720)
    recurrence: Recurrence = "none"
    shift_date: Optional[date] = None


class EventTimerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_key: Optional[str] = None
    label: str
    target_time: datetime
    pre_alert_minutes: int
    recurrence: str
    pre_alert_fired_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    dismissed_by: Optional[UUID] = None
    created_by: Optional[UUID] = None
    shift_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class EventTimerList(BaseModel):
    items: list[EventTimerRead]
