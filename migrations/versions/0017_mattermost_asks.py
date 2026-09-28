"""mattermost asks, ask results and on-demand full-history jobs

Revision ID: 0017_mattermost_asks
Revises: 0016_mattermost_archive
Create Date: 2026-09-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_mattermost_asks"
down_revision: Union[str, None] = "0016_mattermost_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "mattermost_ask",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("question", sa.Text()),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("refresh_minutes", sa.Integer()),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(length=20)),
        sa.Column("last_error", sa.Text()),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
    )
    op.create_index("ix_mattermost_ask_next_run_at", "mattermost_ask", ["next_run_at"])
    op.create_table(
        "mattermost_ask_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ask_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mattermost_ask.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mm_post_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_name", sa.String(length=200)),
        sa.Column("channel_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("thread_title", sa.Text()),
        sa.Column("thread_started_at", sa.DateTime(timezone=True)),
        sa.Column("author", sa.String(length=200)),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("extracted", sa.Text()),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("permalink", sa.Text()),
        sa.UniqueConstraint("ask_id", "mm_post_id", name="uq_mattermost_ask_result_post"),
    )
    op.create_index(
        "ix_mattermost_ask_result_ask_posted", "mattermost_ask_result", ["ask_id", "posted_at"]
    )
    op.create_table(
        "mattermost_history_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("channel_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failed_channel_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True)),
        *_timestamps(),
    )
    op.create_index(
        "ix_mattermost_history_job_status", "mattermost_history_job", ["status", "run_after"]
    )


def downgrade() -> None:
    op.drop_table("mattermost_history_job")
    op.drop_table("mattermost_ask_result")
    op.drop_table("mattermost_ask")
