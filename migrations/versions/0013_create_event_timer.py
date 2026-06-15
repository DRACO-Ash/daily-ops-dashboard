"""create event_timer table

Revision ID: 0013_event_timer
Revises: 0012_event_summary
Create Date: 2026-06-15

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_event_timer"
down_revision: Union[str, None] = "0012_event_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_timer",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=200), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("target_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "pre_alert_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("5"),
        ),
        sa.Column("pre_alert_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("shift_date", sa.Date(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dismissed_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_timer_target_time", "event_timer", ["target_time"])
    op.create_index("ix_event_timer_dismissed_at", "event_timer", ["dismissed_at"])
    op.create_index("ix_event_timer_event_key", "event_timer", ["event_key"])


def downgrade() -> None:
    op.drop_index("ix_event_timer_event_key", table_name="event_timer")
    op.drop_index("ix_event_timer_dismissed_at", table_name="event_timer")
    op.drop_index("ix_event_timer_target_time", table_name="event_timer")
    op.drop_table("event_timer")
