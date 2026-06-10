import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Maneuver(Base, TimestampMixin):
    """UDL maneuver record uploaded by fusion providers.

    Typed columns mirror the commonly-queried fields of the UDL
    maneuver schema; everything else is preserved verbatim in `raw`
    so anything not promoted is still queryable via JSONB ops.
    """

    __tablename__ = "maneuver"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    udl_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    data_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    classification_marking: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    orig_network: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    origin: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    udl_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sat_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_start_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    event_stop_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    mnvr_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delta_v: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thrust_magnitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    thrust_duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    propulsion_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    maneuver_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    responsible_nation: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("udl_id", name="uq_maneuver_udl_id"),
        Index("ix_maneuver_sat_no", "sat_no"),
        Index("ix_maneuver_event_start_time", "event_start_time"),
        Index("ix_maneuver_mnvr_type", "mnvr_type"),
        Index("ix_maneuver_udl_created_at", "udl_created_at"),
    )
