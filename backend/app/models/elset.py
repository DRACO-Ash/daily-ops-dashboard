import uuid

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class Elset(Base, TimestampMixin):
    __tablename__ = "elset"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    udl_id = Column(String(64), nullable=True)

    sat_no = Column(Integer, nullable=False)
    epoch = Column(DateTime(timezone=True), nullable=False)

    mean_motion = Column(Float, nullable=True)
    eccentricity = Column(Float, nullable=True)
    inclination = Column(Float, nullable=True)
    raan = Column(Float, nullable=True)
    arg_of_perigee = Column(Float, nullable=True)
    mean_anomaly = Column(Float, nullable=True)

    rev_no = Column(Integer, nullable=True)
    bstar = Column(Float, nullable=True)
    mean_motion_dot = Column(Float, nullable=True)
    mean_motion_ddot = Column(Float, nullable=True)

    semi_major_axis = Column(Float, nullable=True)
    period = Column(Float, nullable=True)
    apogee = Column(Float, nullable=True)
    perigee = Column(Float, nullable=True)

    line1 = Column(String(70), nullable=True)
    line2 = Column(String(70), nullable=True)

    classification_marking = Column(String(50), nullable=True)
    data_mode = Column(String(20), nullable=True)
    source = Column(String(100), nullable=True)

    raw = Column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("udl_id", name="uq_elset_udl_id"),
        Index("ix_elset_sat_no", "sat_no"),
        Index("ix_elset_epoch", "epoch"),
        Index("ix_elset_sat_no_epoch", "sat_no", "epoch"),
    )
