import uuid

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base import Base, TimestampMixin


class Notso(Base, TimestampMixin):
    __tablename__ = "notso"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    udl_id = Column(String(64), nullable=True)

    notice_id = Column(String(100), nullable=True)
    msg_type = Column(String(50), nullable=True)

    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_until = Column(DateTime(timezone=True), nullable=True)

    subject = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)

    sat_no = Column(Integer, nullable=True)
    region = Column(String(255), nullable=True)

    classification_marking = Column(String(50), nullable=True)
    data_mode = Column(String(20), nullable=True)
    source = Column(String(100), nullable=True)

    udl_created_at = Column(DateTime(timezone=True), nullable=True)

    raw = Column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("udl_id", name="uq_notso_udl_id"),
        Index("ix_notso_notice_id", "notice_id"),
        Index("ix_notso_msg_type", "msg_type"),
        Index("ix_notso_effective_from", "effective_from"),
        Index("ix_notso_sat_no", "sat_no"),
    )
