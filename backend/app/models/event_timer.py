import uuid
from datetime import date as date_t
from datetime import datetime
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class EventTimer(Base, TimestampMixin):
    """Operator-set countdown to an upcoming event.

    The frontend fires an audible + visual pre-alert at
    `target_time - pre_alert_minutes`, then recurring alerts every
    cycle from `target_time` until `dismissed_at` is set.

    Lifecycle:
    ● upcoming: now < target_time - pre_alert_minutes
    ● pre-alert: target_time - pre_alert_minutes <= now < target_time;
      one-shot warning, dampened by pre_alert_fired_at
    ● firing: now >= target_time and dismissed_at is null
    ● dismissed: dismissed_at is set; recurring alerts stop
    """

    __tablename__ = "event_timer"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    event_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pre_alert_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)

    pre_alert_fired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_date: Mapped[Optional[date_t]] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_event_timer_target_time", "target_time"),
        Index("ix_event_timer_dismissed_at", "dismissed_at"),
        Index("ix_event_timer_event_key", "event_key"),
    )
