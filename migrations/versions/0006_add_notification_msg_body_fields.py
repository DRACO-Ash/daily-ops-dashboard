"""add notification columns derived from msgBody

Revision ID: 0006_notif_msgbody
Revises: 0005_rename_notso
Create Date: 2026-06-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_notif_msgbody"
down_revision: Union[str, None] = "0005_rename_notso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("notso_identifier", sa.String(length=100), nullable=True),
    )
    op.add_column("notification", sa.Column("event_class", sa.String(length=500), nullable=True))
    op.add_column("notification", sa.Column("event_type", sa.String(length=50), nullable=True))
    op.add_column("notification", sa.Column("event_id", sa.String(length=64), nullable=True))
    op.add_column("notification", sa.Column("status", sa.String(length=20), nullable=True))
    op.add_column(
        "notification", sa.Column("publish_date", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("notification", sa.Column("company_name", sa.String(length=100), nullable=True))
    op.add_column("notification", sa.Column("notso_link", sa.Text(), nullable=True))
    op.add_column(
        "notification",
        sa.Column("sat_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("notification", sa.Column("created_by", sa.String(length=100), nullable=True))
    op.add_column("notification", sa.Column("orig_network", sa.String(length=50), nullable=True))

    op.create_index("ix_notification_notso_identifier", "notification", ["notso_identifier"])
    op.create_index("ix_notification_status", "notification", ["status"])
    op.create_index("ix_notification_event_type", "notification", ["event_type"])
    op.create_index("ix_notification_publish_date", "notification", ["publish_date"])


def downgrade() -> None:
    op.drop_index("ix_notification_publish_date", table_name="notification")
    op.drop_index("ix_notification_event_type", table_name="notification")
    op.drop_index("ix_notification_status", table_name="notification")
    op.drop_index("ix_notification_notso_identifier", table_name="notification")

    op.drop_column("notification", "orig_network")
    op.drop_column("notification", "created_by")
    op.drop_column("notification", "sat_ids")
    op.drop_column("notification", "notso_link")
    op.drop_column("notification", "company_name")
    op.drop_column("notification", "publish_date")
    op.drop_column("notification", "status")
    op.drop_column("notification", "event_id")
    op.drop_column("notification", "event_type")
    op.drop_column("notification", "event_class")
    op.drop_column("notification", "notso_identifier")
