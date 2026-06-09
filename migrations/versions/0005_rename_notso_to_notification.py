"""rename notso to notification

Revision ID: 0005_rename_notso
Revises: 0004_create_notso
Create Date: 2026-05-28

"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_rename_notso"
down_revision: Union[str, None] = "0004_create_notso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("notso", "notification")
    op.execute("ALTER INDEX ix_notso_notice_id RENAME TO ix_notification_notice_id")
    op.execute("ALTER INDEX ix_notso_msg_type RENAME TO ix_notification_msg_type")
    op.execute("ALTER INDEX ix_notso_effective_from RENAME TO ix_notification_effective_from")
    op.execute("ALTER INDEX ix_notso_sat_no RENAME TO ix_notification_sat_no")
    op.execute(
        "ALTER TABLE notification RENAME CONSTRAINT uq_notso_udl_id TO uq_notification_udl_id"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE notification RENAME CONSTRAINT uq_notification_udl_id TO uq_notso_udl_id"
    )
    op.execute("ALTER INDEX ix_notification_sat_no RENAME TO ix_notso_sat_no")
    op.execute("ALTER INDEX ix_notification_effective_from RENAME TO ix_notso_effective_from")
    op.execute("ALTER INDEX ix_notification_msg_type RENAME TO ix_notso_msg_type")
    op.execute("ALTER INDEX ix_notification_notice_id RENAME TO ix_notso_notice_id")
    op.rename_table("notification", "notso")
