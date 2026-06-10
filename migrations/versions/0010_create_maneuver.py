"""create maneuver table

Revision ID: 0010_create_maneuver
Revises: 0009_assist_eval
Create Date: 2026-06-10

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_create_maneuver"
down_revision: Union[str, None] = "0009_assist_eval"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "maneuver",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("udl_id", sa.String(length=64), nullable=True),
        sa.Column("data_mode", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("classification_marking", sa.String(length=50), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("orig_network", sa.String(length=50), nullable=True),
        sa.Column("origin", sa.String(length=100), nullable=True),
        sa.Column("udl_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sat_no", sa.Integer(), nullable=True),
        sa.Column("event_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_stop_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mnvr_type", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("delta_v", sa.Float(), nullable=True),
        sa.Column("thrust_magnitude", sa.Float(), nullable=True),
        sa.Column("thrust_duration", sa.Float(), nullable=True),
        sa.Column("propulsion_type", sa.String(length=50), nullable=True),
        sa.Column("maneuver_status", sa.String(length=50), nullable=True),
        sa.Column("responsible_nation", sa.String(length=50), nullable=True),
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
        sa.UniqueConstraint("udl_id", name="uq_maneuver_udl_id"),
    )
    op.create_index("ix_maneuver_sat_no", "maneuver", ["sat_no"])
    op.create_index("ix_maneuver_event_start_time", "maneuver", ["event_start_time"])
    op.create_index("ix_maneuver_mnvr_type", "maneuver", ["mnvr_type"])
    op.create_index("ix_maneuver_udl_created_at", "maneuver", ["udl_created_at"])


def downgrade() -> None:
    op.drop_index("ix_maneuver_udl_created_at", table_name="maneuver")
    op.drop_index("ix_maneuver_mnvr_type", table_name="maneuver")
    op.drop_index("ix_maneuver_event_start_time", table_name="maneuver")
    op.drop_index("ix_maneuver_sat_no", table_name="maneuver")
    op.drop_table("maneuver")
