"""create mattermost_message table

Revision ID: 0015_mattermost
Revises: 0014_timer_recurrence
Create Date: 2026-06-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_mattermost"
down_revision: Union[str, None] = "0014_timer_recurrence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mattermost_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mm_post_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("user_display_name", sa.String(length=200), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("post_type", sa.String(length=50), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mm_post_id", name="uq_mattermost_message_post_id"),
    )
    op.create_index("ix_mattermost_message_channel_id", "mattermost_message", ["channel_id"])
    op.create_index("ix_mattermost_message_posted_at", "mattermost_message", ["posted_at"])
    op.create_index("ix_mattermost_message_user_id", "mattermost_message", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mattermost_message_user_id", table_name="mattermost_message")
    op.drop_index("ix_mattermost_message_posted_at", table_name="mattermost_message")
    op.drop_index("ix_mattermost_message_channel_id", table_name="mattermost_message")
    op.drop_table("mattermost_message")
