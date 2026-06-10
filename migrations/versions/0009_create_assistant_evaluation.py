"""create assistant_evaluation table

Revision ID: 0009_assist_eval
Revises: 0008_create_procedure
Create Date: 2026-06-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_assist_eval"
down_revision: Union[str, None] = "0008_create_procedure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_evaluation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("structured", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("procedures_used", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["notification_id"], ["notification.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_evaluation_notification",
        "assistant_evaluation",
        ["notification_id"],
    )
    op.create_index(
        "ix_assistant_evaluation_evaluated_at",
        "assistant_evaluation",
        ["evaluated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_evaluation_evaluated_at", table_name="assistant_evaluation")
    op.drop_index("ix_assistant_evaluation_notification", table_name="assistant_evaluation")
    op.drop_table("assistant_evaluation")
