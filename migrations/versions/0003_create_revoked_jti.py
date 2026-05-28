"""create revoked_jti table

Revision ID: 0003_create_revoked_jti
Revises: 0002_create_user
Create Date: 2026-05-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_create_revoked_jti"
down_revision: Union[str, None] = "0002_create_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revoked_jti",
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("ix_revoked_jti_user_id", "revoked_jti", ["user_id"])
    op.create_index("ix_revoked_jti_expires_at", "revoked_jti", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_revoked_jti_expires_at", table_name="revoked_jti")
    op.drop_index("ix_revoked_jti_user_id", table_name="revoked_jti")
    op.drop_table("revoked_jti")
