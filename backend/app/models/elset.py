import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Elset(Base, TimestampMixin):
    __tablename__ = "elset"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    udl_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    sat_no: Mapped[int] = mapped_column(Integer, nullable=False)
    epoch: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    mean_motion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eccentricity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inclination: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raan: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arg_of_perigee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_anomaly: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    rev_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bstar: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_motion_dot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mean_motion_ddot: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    semi_major_axis: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    period: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    apogee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    perigee: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    line1: Mapped[Optional[str]] = mapped_column(String(70), nullable=True)
    line2: Mapped[Optional[str]] = mapped_column(String(70), nullable=True)

    classification_marking: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    data_mode: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("udl_id", name="uq_elset_udl_id"),
        Index("ix_elset_sat_no", "sat_no"),
        Index("ix_elset_epoch", "epoch"),
        Index("ix_elset_sat_no_epoch", "sat_no", "epoch"),
    )
