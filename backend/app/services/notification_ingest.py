import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.notification import Notification
from app.services.audit import write_audit
from app.services.udl_client import UDLClient


@dataclass
class NotificationIngestResult:
    pulled: int
    inserted: int
    updated: int
    skipped: int


UDL_TO_MODEL_FIELDS: dict[str, str] = {
    "noticeId": "notice_id",
    "noticeNumber": "notice_id",
    "msgType": "msg_type",
    "effectiveFrom": "effective_from",
    "effectiveUntil": "effective_until",
    "expirationTime": "effective_until",
    "subject": "subject",
    "description": "description",
    "text": "description",
    "satNo": "sat_no",
    "region": "region",
    "classificationMarking": "classification_marking",
    "dataMode": "data_mode",
    "source": "source",
    "createdAt": "udl_created_at",
}

DATETIME_FIELDS: set[str] = {
    "effectiveFrom",
    "effectiveUntil",
    "expirationTime",
    "createdAt",
}

UPDATABLE_COLUMNS: list[str] = [
    "notice_id",
    "msg_type",
    "effective_from",
    "effective_until",
    "subject",
    "description",
    "sat_no",
    "region",
    "classification_marking",
    "data_mode",
    "source",
    "udl_created_at",
    "raw",
]


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _map_udl_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    udl_id = record.get("id")
    if not udl_id:
        return None

    mapped: dict[str, Any] = {
        "udl_id": str(udl_id),
        "raw": record,
    }
    for udl_field, model_field in UDL_TO_MODEL_FIELDS.items():
        if udl_field not in record:
            continue
        value = record[udl_field]
        if udl_field in DATETIME_FIELDS and isinstance(value, str):
            value = _parse_datetime(value)
        mapped[model_field] = value
    return mapped


async def ingest_notifications(
    db: AsyncSession,
    client: UDLClient,
    msg_type: Optional[str] = None,
    created_at_gte: Optional[datetime] = None,
    data_mode: Optional[str] = None,
    source: Optional[str] = None,
    max_results: Optional[int] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
) -> NotificationIngestResult:
    records = await client.get_notifications(
        msg_type=msg_type,
        created_at_gte=created_at_gte,
        data_mode=data_mode,
        source=source,
        max_results=max_results,
    )

    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw in records:
        mapped = _map_udl_record(raw)
        if mapped is None:
            skipped += 1
            continue
        rows.append(mapped)

    inserted = 0
    updated = 0

    if rows:
        existing_result = await db.execute(
            select(Notification.udl_id).where(Notification.udl_id.in_([r["udl_id"] for r in rows]))
        )
        existing_ids = {row[0] for row in existing_result.all()}

        stmt = pg_insert(Notification).values(rows)
        update_cols: dict[str, Any] = {
            col: getattr(stmt.excluded, col) for col in UPDATABLE_COLUMNS
        }
        update_cols["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            constraint="uq_notification_udl_id",
            set_=update_cols,
        )
        await db.execute(stmt)

        inserted = sum(1 for r in rows if r["udl_id"] not in existing_ids)
        updated = sum(1 for r in rows if r["udl_id"] in existing_ids)

    result = NotificationIngestResult(
        pulled=len(records),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )

    await write_audit(
        db,
        action_type="udl.notification.ingest",
        entity_type="notification_ingest_run",
        user_id=user_id,
        ip_address=ip_address,
        detail={
            "msg_type": msg_type,
            "created_at_gte": (created_at_gte.isoformat() if created_at_gte else None),
            "data_mode": data_mode,
            "source": source,
            "max_results": max_results,
            "pulled": result.pulled,
            "inserted": result.inserted,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )
    await db.commit()

    return result
