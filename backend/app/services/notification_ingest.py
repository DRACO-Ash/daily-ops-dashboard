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


UPDATABLE_COLUMNS: list[str] = [
    "msg_type",
    "data_mode",
    "source",
    "classification_marking",
    "created_by",
    "orig_network",
    "udl_created_at",
    "notso_identifier",
    "notice_id",
    "event_id",
    "event_class",
    "event_type",
    "status",
    "subject",
    "description",
    "region",
    "notso_link",
    "company_name",
    "publish_date",
    "effective_from",
    "effective_until",
    "sat_no",
    "sat_ids",
    "raw",
]


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and value == "":
        return
    target[key] = value


def _set_datetime_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "":
        return
    if isinstance(value, datetime):
        target[key] = value
        return
    if isinstance(value, str):
        try:
            target[key] = _parse_datetime(value)
        except ValueError:
            pass


def _coerce_sat_no(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _map_udl_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    udl_id = record.get("id")
    if not udl_id:
        return None

    mapped: dict[str, Any] = {
        "udl_id": str(udl_id),
        "raw": record,
    }

    # Top-level UDL envelope
    _set_if_present(mapped, "msg_type", record.get("msgType"))
    _set_if_present(mapped, "data_mode", record.get("dataMode"))
    _set_if_present(mapped, "source", record.get("source"))
    _set_if_present(mapped, "classification_marking", record.get("classificationMarking"))
    _set_if_present(mapped, "created_by", record.get("createdBy"))
    _set_if_present(mapped, "orig_network", record.get("origNetwork"))
    _set_datetime_if_present(mapped, "udl_created_at", record.get("createdAt"))

    # Nested msgBody fields (TACREP_NOTSO shape, also tolerant to others)
    msg_body = record.get("msgBody")
    if isinstance(msg_body, dict):
        _set_if_present(mapped, "notso_identifier", msg_body.get("NOTSO"))
        _set_if_present(mapped, "notice_id", msg_body.get("NOTSO"))
        _set_if_present(mapped, "event_class", msg_body.get("Event_Class"))
        _set_if_present(mapped, "subject", msg_body.get("Event_Class"))
        _set_if_present(mapped, "event_type", msg_body.get("Event_Type"))
        _set_if_present(mapped, "event_id", msg_body.get("Event_Id"))
        _set_if_present(mapped, "status", msg_body.get("Status"))
        _set_if_present(mapped, "description", msg_body.get("Event_Description"))
        _set_if_present(mapped, "company_name", msg_body.get("Company_Name"))
        _set_if_present(mapped, "notso_link", msg_body.get("NOTSO_Link"))
        _set_datetime_if_present(mapped, "publish_date", msg_body.get("Publish_Date"))

        sat_ids = msg_body.get("SatIds")
        if isinstance(sat_ids, list) and sat_ids:
            mapped["sat_ids"] = sat_ids
            if len(sat_ids) == 1:
                coerced = _coerce_sat_no(sat_ids[0])
                if coerced is not None:
                    mapped["sat_no"] = coerced

    # Flat-shaped fallbacks for non-TACREP_NOTSO msgTypes that may
    # surface in the same endpoint.
    if "notice_id" not in mapped:
        _set_if_present(mapped, "notice_id", record.get("noticeId"))
    if "notice_id" not in mapped:
        _set_if_present(mapped, "notice_id", record.get("noticeNumber"))
    if "subject" not in mapped:
        _set_if_present(mapped, "subject", record.get("subject"))
    if "description" not in mapped:
        _set_if_present(mapped, "description", record.get("description"))
    if "description" not in mapped:
        _set_if_present(mapped, "description", record.get("text"))
    _set_if_present(mapped, "region", record.get("region"))
    _set_datetime_if_present(mapped, "effective_from", record.get("effectiveFrom"))
    if "effective_until" not in mapped:
        _set_datetime_if_present(mapped, "effective_until", record.get("effectiveUntil"))
    if "effective_until" not in mapped:
        _set_datetime_if_present(mapped, "effective_until", record.get("expirationTime"))

    if "sat_no" not in mapped:
        coerced = _coerce_sat_no(record.get("satNo"))
        if coerced is not None:
            mapped["sat_no"] = coerced

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
