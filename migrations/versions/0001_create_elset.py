"""create elset table

Revision ID: 0001_create_elset
Revises:
Create Date: 2026-05-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_create_elset"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "elset",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("udl_id", sa.String(length=64), nullable=True),
        sa.Column("sat_no", sa.Integer(), nullable=False),
        sa.Column("epoch", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mean_motion", sa.Float(), nullable=True),
        sa.Column("eccentricity", sa.Float(), nullable=True),
        sa.Column("inclination", sa.Float(), nullable=True),
        sa.Column("raan", sa.Float(), nullable=True),
        sa.Column("arg_of_perigee", sa.Float(), nullable=True),
        sa.Column("mean_anomaly", sa.Float(), nullable=True),
        sa.Column("rev_no", sa.Integer(), nullable=True),
        sa.Column("bstar", sa.Float(), nullable=True),
        sa.Column("mean_motion_dot", sa.Float(), nullable=True),
        sa.Column("mean_motion_ddot", sa.Float(), nullable=True),
        sa.Column("semi_major_axis", sa.Float(), nullable=True),
        sa.Column("period", sa.Float(), nullable=True),
        sa.Column("apogee", sa.Float(), nullable=True),
        sa.Column("perigee", sa.Float(), nullable=True),
        sa.Column("line1", sa.String(length=70), nullable=True),
        sa.Column("line2", sa.String(length=70), nullable=True),
        sa.Column("classification_marking", sa.String(length=50), nullable=True),
        sa.Column("data_mode", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
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
        sa.UniqueConstraint("udl_id", name="uq_elset_udl_id"),
    )
    op.create_index("ix_elset_sat_no", "elset", ["sat_no"])
    op.create_index("ix_elset_epoch", "elset", ["epoch"])
    op.create_index("ix_elset_sat_no_epoch", "elset", ["sat_no", "epoch"])


def downgrade() -> None:
    op.drop_index("ix_elset_sat_no_epoch", table_name="elset")
    op.drop_index("ix_elset_epoch", table_name="elset")
    op.drop_index("ix_elset_sat_no", table_name="elset")
    op.drop_table("elset")
