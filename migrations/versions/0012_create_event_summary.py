"""create event_summary table

Revision ID: 0012_event_summary
Revises: 0011_shift_log
Create Date: 2026-06-12

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_event_summary"
down_revision: Union[str, None] = "0011_shift_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_summary",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column(
            "source_notification_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("latest_notification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "publication_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["latest_notification_id"], ["notification.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_key", name="uq_event_summary_event_key"),
    )
    op.create_index(
        "ix_event_summary_latest_notification",
        "event_summary",
        ["latest_notification_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_summary_latest_notification", table_name="event_summary")
    op.drop_table("event_summary")
