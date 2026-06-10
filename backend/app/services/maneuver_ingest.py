import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.maneuver import Maneuver
from app.services.audit import write_audit
from app.services.udl_client import UDLClient


@dataclass
class ManeuverIngestResult:
    pulled: int
    inserted: int
    updated: int
    skipped: int


UPDATABLE_COLUMNS: list[str] = [
    "data_mode",
    "source",
    "classification_marking",
    "created_by",
    "orig_network",
    "origin",
    "udl_created_at",
    "sat_no",
    "event_start_time",
    "event_stop_time",
    "mnvr_type",
    "description",
    "delta_v",
    "thrust_magnitude",
    "thrust_duration",
    "propulsion_type",
    "maneuver_status",
    "responsible_nation",
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


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
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

    _set_if_present(mapped, "data_mode", record.get("dataMode"))
    _set_if_present(mapped, "source", record.get("source"))
    _set_if_present(mapped, "classification_marking", record.get("classificationMarking"))
    _set_if_present(mapped, "created_by", record.get("createdBy"))
    _set_if_present(mapped, "orig_network", record.get("origNetwork"))
    _set_if_present(mapped, "origin", record.get("origin"))
    _set_datetime_if_present(mapped, "udl_created_at", record.get("createdAt"))

    sat_no = _coerce_int(record.get("satNo"))
    if sat_no is not None:
        mapped["sat_no"] = sat_no

    _set_datetime_if_present(mapped, "event_start_time", record.get("eventStartTime"))
    _set_datetime_if_present(mapped, "event_stop_time", record.get("eventStopTime"))
    _set_if_present(mapped, "mnvr_type", record.get("mnvrType"))
    _set_if_present(mapped, "description", record.get("description"))

    delta_v = _coerce_float(record.get("deltaV"))
    if delta_v is not None:
        mapped["delta_v"] = delta_v
    thrust_mag = _coerce_float(record.get("thrustMag"))
    if thrust_mag is not None:
        mapped["thrust_magnitude"] = thrust_mag
    thrust_dur = _coerce_float(record.get("thrustDuration"))
    if thrust_dur is not None:
        mapped["thrust_duration"] = thrust_dur

    _set_if_present(mapped, "propulsion_type", record.get("propulsionType"))
    _set_if_present(mapped, "maneuver_status", record.get("maneuverStatus"))
    _set_if_present(mapped, "responsible_nation", record.get("responsibleNation"))

    return mapped


async def ingest_maneuvers(
    db: AsyncSession,
    client: UDLClient,
    event_start_time_gte: datetime,
    sat_no: Optional[int] = None,
    data_mode: Optional[str] = None,
    max_results: Optional[int] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
) -> ManeuverIngestResult:
    records = await client.get_maneuvers(
        event_start_time_gte=event_start_time_gte,
        sat_no=sat_no,
        data_mode=data_mode,
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
        # Same multi-row VALUES requirement as the other ingest paths:
        # union the keysets and backfill missing keys with None.
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.keys())
        for r in rows:
            for key in all_keys:
                r.setdefault(key, None)

        existing_result = await db.execute(
            select(Maneuver.udl_id).where(Maneuver.udl_id.in_([r["udl_id"] for r in rows]))
        )
        existing_ids = {row[0] for row in existing_result.all()}

        stmt = pg_insert(Maneuver).values(rows)
        update_cols: dict[str, Any] = {
            col: getattr(stmt.excluded, col) for col in UPDATABLE_COLUMNS
        }
        update_cols["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            constraint="uq_maneuver_udl_id",
            set_=update_cols,
        )
        await db.execute(stmt)

        inserted = sum(1 for r in rows if r["udl_id"] not in existing_ids)
        updated = sum(1 for r in rows if r["udl_id"] in existing_ids)

    result = ManeuverIngestResult(
        pulled=len(records),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )

    await write_audit(
        db,
        action_type="udl.maneuver.ingest",
        entity_type="maneuver_ingest_run",
        user_id=user_id,
        ip_address=ip_address,
        detail={
            "event_start_time_gte": event_start_time_gte.isoformat(),
            "sat_no": sat_no,
            "data_mode": data_mode,
            "max_results": max_results,
            "pulled": result.pulled,
            "inserted": result.inserted,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )
    await db.commit()

    return result
