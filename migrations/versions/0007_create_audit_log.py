"""create audit schema and audit_log table

Revision ID: 0007_create_audit_log
Revises: 0006_notif_msgbody
Create Date: 2026-06-09

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_create_audit_log"
down_revision: Union[str, None] = "0006_notif_msgbody"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS audit")
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="audit",
    )
    # The chain-write path reads the latest entry's hash via
    # ORDER BY timestamp DESC LIMIT 1; index makes that a constant-time
    # lookup even as the log grows.
    op.create_index(
        "ix_audit_log_timestamp",
        "audit_log",
        [sa.text("timestamp DESC")],
        schema="audit",
    )
    op.create_index("ix_audit_log_action_type", "audit_log", ["action_type"], schema="audit")
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"], schema="audit")


def downgrade() -> None:
    op.drop_index("ix_audit_log_user_id", table_name="audit_log", schema="audit")
    op.drop_index("ix_audit_log_action_type", table_name="audit_log", schema="audit")
    op.drop_index("ix_audit_log_timestamp", table_name="audit_log", schema="audit")
    op.drop_table("audit_log", schema="audit")
    op.execute("DROP SCHEMA IF EXISTS audit")
