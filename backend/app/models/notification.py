import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """Generic UDL notification record.

    Covers Tactical Reports (TACREP) and Notices to Space Operators
    (NOTSO), both of which UDL serves through the same `/notification`
    endpoint under `msgType=TACREP_NOTSO`. Other UDL notification
    msgType values land in the same table.

    UDL nests the interesting fields inside a `msgBody` object. The
    typed columns below mirror the `msgBody` shape observed in
    TACREP_NOTSO responses (see migration `0006`); the raw payload is
    still preserved verbatim in `raw` so anything we have not pulled
    into a column is still queryable via JSONB ops.
    """

    __tablename__ = "notification"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    udl_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Top-level UDL envelope
    msg_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    data_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    classification_marking: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    orig_network: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    udl_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # msgBody-derived identifiers
    notso_identifier: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    event_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # msgBody-derived classification of the event
    event_class: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    event_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # msgBody-derived content
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notso_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    company_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Time fields
    publish_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Associated satellite(s). `sat_no` is a convenience for single-sat
    # notices; `sat_ids` holds the full list for multi-sat notices.
    sat_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sat_ids: Mapped[Optional[list[str]]] = mapped_column(JSONB, nullable=True)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("udl_id", name="uq_notification_udl_id"),
        Index("ix_notification_notice_id", "notice_id"),
        Index("ix_notification_msg_type", "msg_type"),
        Index("ix_notification_effective_from", "effective_from"),
        Index("ix_notification_sat_no", "sat_no"),
        Index("ix_notification_notso_identifier", "notso_identifier"),
        Index("ix_notification_status", "status"),
        Index("ix_notification_event_type", "event_type"),
        Index("ix_notification_publish_date", "publish_date"),
    )
