import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MattermostMessage(Base, TimestampMixin):
    """A single message ingested from a configured Mattermost channel.

    Identified uniquely by `mm_post_id` — Mattermost's internal post id.
    `user_display_name` is cached at ingest time so the read path
    doesn't need a separate /users/{id} call; we accept staleness if a
    user changes their display name.
    """

    __tablename__ = "mattermost_message"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    mm_post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    post_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    root_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    mm_updated_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("mm_post_id", name="uq_mattermost_message_post_id"),
        Index("ix_mattermost_message_channel_id", "channel_id"),
        Index("ix_mattermost_message_posted_at", "posted_at"),
        Index("ix_mattermost_message_user_id", "user_id"),
    )


class MattermostChannelState(Base, TimestampMixin):
    """Per-channel ingest progress.

    `watermark_ms` is the highest Mattermost `update_at` stored, used as
    the `since` for incremental pulls so edits and deletions arrive too.
    `backfill_cursor` is the oldest post id reached while walking history
    backwards; it only moves further back, so posts arriving mid-backfill
    cannot shift a page and open a gap.
    """

    __tablename__ = "mattermost_channel_state"

    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    watermark_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    backfill_cursor: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    backfill_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
