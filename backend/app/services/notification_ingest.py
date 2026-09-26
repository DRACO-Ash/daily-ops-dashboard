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


# (column, UDL key) pairs. Order matters where two keys feed one column:
# the first present value wins.
_ENVELOPE_FIELDS = (
    ("msg_type", "msgType"),
    ("data_mode", "dataMode"),
    ("source", "source"),
    ("classification_marking", "classificationMarking"),
    ("created_by", "createdBy"),
    ("orig_network", "origNetwork"),
)
_MSG_BODY_FIELDS = (
    ("notso_identifier", "NOTSO"),
    ("notice_id", "NOTSO"),
    ("event_class", "Event_Class"),
    ("subject", "Event_Class"),
    ("event_type", "Event_Type"),
    ("event_id", "Event_Id"),
    ("status", "Status"),
    ("description", "Event_Description"),
    ("company_name", "Company_Name"),
    ("notso_link", "NOTSO_Link"),
)
# Flat-shaped fallbacks for non-TACREP_NOTSO msgTypes that may surface
# in the same endpoint. Only fill columns msgBody left empty.
_FLAT_FALLBACK_FIELDS = (
    ("notice_id", "noticeId"),
    ("notice_id", "noticeNumber"),
    ("subject", "subject"),
    ("description", "description"),
    ("description", "text"),
    ("region", "region"),
)
_FLAT_FALLBACK_DATETIMES = (
    ("effective_from", "effectiveFrom"),
    ("effective_until", "effectiveUntil"),
    ("effective_until", "expirationTime"),
)


def _fill_missing(mapped: dict[str, Any], source: dict[str, Any], fields) -> None:
    for column, key in fields:
        if column not in mapped:
            _set_if_present(mapped, column, source.get(key))


def _map_sat_ids(mapped: dict[str, Any], sat_ids: Any) -> None:
    if not isinstance(sat_ids, list) or not sat_ids:
        return
    mapped["sat_ids"] = sat_ids
    if len(sat_ids) == 1:
        coerced = _coerce_sat_no(sat_ids[0])
        if coerced is not None:
            mapped["sat_no"] = coerced


def _map_udl_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    udl_id = record.get("id")
    if not udl_id:
        return None

    mapped: dict[str, Any] = {
        "udl_id": str(udl_id),
        "raw": record,
    }

    # Top-level UDL envelope
    _fill_missing(mapped, record, _ENVELOPE_FIELDS)
    _set_datetime_if_present(mapped, "udl_created_at", record.get("createdAt"))

    # Nested msgBody fields (TACREP_NOTSO shape, also tolerant to others)
    msg_body = record.get("msgBody")
    if isinstance(msg_body, dict):
        _fill_missing(mapped, msg_body, _MSG_BODY_FIELDS)
        _set_datetime_if_present(mapped, "publish_date", msg_body.get("Publish_Date"))
        _map_sat_ids(mapped, msg_body.get("SatIds"))

    _fill_missing(mapped, record, _FLAT_FALLBACK_FIELDS)
    for column, key in _FLAT_FALLBACK_DATETIMES:
        if column not in mapped:
            _set_datetime_if_present(mapped, column, record.get(key))

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
        # SQLAlchemy requires every row in a multi-row VALUES clause to
        # share the same column set. Real UDL responses have varied
        # shapes per record (e.g. only some carry SatIds), so backfill
        # missing keys with None before compiling.
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.keys())
        for r in rows:
            for key in all_keys:
                r.setdefault(key, None)

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
