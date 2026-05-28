"""create notso table

Revision ID: 0004_create_notso
Revises: 0003_create_revoked_jti
Create Date: 2026-05-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_create_notso"
down_revision: Union[str, None] = "0003_create_revoked_jti"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notso",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("udl_id", sa.String(length=64), nullable=True),
        sa.Column("notice_id", sa.String(length=100), nullable=True),
        sa.Column("msg_type", sa.String(length=50), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sat_no", sa.Integer(), nullable=True),
        sa.Column("region", sa.String(length=255), nullable=True),
        sa.Column("classification_marking", sa.String(length=50), nullable=True),
        sa.Column("data_mode", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("udl_created_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("udl_id", name="uq_notso_udl_id"),
    )
    op.create_index("ix_notso_notice_id", "notso", ["notice_id"])
    op.create_index("ix_notso_msg_type", "notso", ["msg_type"])
    op.create_index("ix_notso_effective_from", "notso", ["effective_from"])
    op.create_index("ix_notso_sat_no", "notso", ["sat_no"])


def downgrade() -> None:
    op.drop_index("ix_notso_sat_no", table_name="notso")
    op.drop_index("ix_notso_effective_from", table_name="notso")
    op.drop_index("ix_notso_msg_type", table_name="notso")
    op.drop_index("ix_notso_notice_id", table_name="notso")
    op.drop_table("notso")
