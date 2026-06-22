"""add recurrence column to event_timer

Revision ID: 0014_timer_recurrence
Revises: 0013_event_timer
Create Date: 2026-06-22

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_timer_recurrence"
down_revision: Union[str, None] = "0013_event_timer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "event_timer",
        sa.Column(
            "recurrence",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("event_timer", "recurrence")
