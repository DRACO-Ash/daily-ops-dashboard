"""Saved Mattermost asks, their results, and on-demand full-history jobs."""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class MattermostAsk(Base, TimestampMixin):
    """A named, reusable pull definition (see schemas.mattermost.AskSpec).

    `next_run_at` is when the background loop should next run it: set to
    now for "run now", left null for "not scheduled". With
    `refresh_minutes` set, each run schedules the next.
    """

    __tablename__ = "mattermost_ask"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    question: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    refresh_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_mattermost_ask_next_run_at", "next_run_at"),)


class MattermostAskResult(Base):
    """One row of an ask's latest result set. Replaced wholesale per run."""

    __tablename__ = "mattermost_ask_result"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ask_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mattermost_ask.id", ondelete="CASCADE"), nullable=False
    )
    mm_post_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    channel_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thread_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extracted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    permalink: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("ask_id", "mm_post_id", name="uq_mattermost_ask_result_post"),
        Index("ix_mattermost_ask_result_ask_posted", "ask_id", "posted_at"),
    )


class MattermostHistoryJob(Base, TimestampMixin):
    """A request to pull the full history of some channels at a chosen time.

    Empty `channel_ids` means every channel the bot belongs to. Progress
    per channel lives in MattermostChannelState, so a job spans as many
    background cycles as it needs.
    """

    __tablename__ = "mattermost_history_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    # Channels that failed (e.g. the bot lost access); skipped for the
    # rest of the job so one bad channel cannot keep it running forever.
    failed_channel_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (Index("ix_mattermost_history_job_status", "status", "run_after"),)
