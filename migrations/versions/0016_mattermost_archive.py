"""mattermost archive: edits, deletions, threads and per-channel state

Revision ID: 0016_mattermost_archive
Revises: 0015_mattermost
Create Date: 2026-09-26

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_mattermost_archive"
down_revision: Union[str, None] = "0015_mattermost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mattermost_message", sa.Column("root_id", sa.String(length=64)))
    op.add_column("mattermost_message", sa.Column("mm_updated_at", sa.BigInteger()))
    op.add_column("mattermost_message", sa.Column("edited_at", sa.DateTime(timezone=True)))
    op.add_column("mattermost_message", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_table(
        "mattermost_channel_state",
        sa.Column("channel_id", sa.String(length=64), nullable=False),
        sa.Column("channel_name", sa.String(length=200), nullable=True),
        sa.Column("watermark_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("backfill_cursor", sa.String(length=64), nullable=True),
        sa.Column("backfill_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.PrimaryKeyConstraint("channel_id"),
    )


def downgrade() -> None:
    op.drop_table("mattermost_channel_state")
    op.drop_column("mattermost_message", "deleted_at")
    op.drop_column("mattermost_message", "edited_at")
    op.drop_column("mattermost_message", "mm_updated_at")
    op.drop_column("mattermost_message", "root_id")
