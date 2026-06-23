from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShiftNoteCreate(BaseModel):
    raw_text: str = Field(min_length=1, max_length=10_000)
    shift_date: Optional[date] = None


class ShiftNoteUpdate(BaseModel):
    polished_text: Optional[str] = Field(default=None, max_length=10_000)


class ShiftNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    author_id: Optional[UUID] = None
    shift_date: date
    raw_text: str
    polished_text: Optional[str] = None
    polish_error: Optional[str] = None
    model: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ShiftNoteList(BaseModel):
    items: list[ShiftNoteRead]
    shift_date: date


class ShiftSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    shift_date: date
    generated_by: Optional[UUID] = None
    narrative: str
    source_note_ids: list[str]
    model: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ShiftDateSummary(BaseModel):
    """A shift date that has at least one note logged against it."""

    shift_date: date
    note_count: int
    has_summary: bool


class ShiftDateList(BaseModel):
    items: list[ShiftDateSummary]
