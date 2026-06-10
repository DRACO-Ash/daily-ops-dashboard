import uuid
from typing import Optional

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Procedure(Base, TimestampMixin):
    """Operator-uploaded operations procedure.

    Procedures are flexible documents the operator uploads through the
    UI. They are stored as files on disk under PROCEDURE_STORAGE_PATH
    and indexed in this table. The reasoning pipeline reads the file
    content at evaluation time and passes it to Claude alongside
    NOTSOs and TLE-derived events so the assistant can recommend
    next-step actions.
    """

    __tablename__ = "procedure"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("file_hash", name="uq_procedure_file_hash"),
        Index("ix_procedure_name", "name"),
    )
