import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AssistantEvaluation(Base):
    """Cached Claude evaluation of a notification against current procedures.

    Stored per-notification so the analyst can pull up the assistant's
    take without re-billing Claude on every page load. The
    `procedures_used` array records which procedure ids were in the
    prompt; if procedures are uploaded or removed, callers can decide
    whether a fresh evaluation is warranted.
    """

    __tablename__ = "assistant_evaluation"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("notification.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    structured: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    procedures_used: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_assistant_evaluation_notification", "notification_id"),
        Index("ix_assistant_evaluation_evaluated_at", "evaluated_at"),
    )
