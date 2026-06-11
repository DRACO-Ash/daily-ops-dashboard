import uuid
from datetime import date as date_t
from typing import Optional

from sqlalchemy import Date, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ShiftSummary(Base, TimestampMixin):
    """End-of-shift narrative composed by Claude from the day's notes."""

    __tablename__ = "shift_summary"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    shift_date: Mapped[date_t] = mapped_column(Date, nullable=False)
    generated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    source_note_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_shift_summary_shift_date", "shift_date"),)
