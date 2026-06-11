import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.elset import Elset
from app.services.audit import write_audit
from app.services.udl_client import UDLClient

logger = logging.getLogger(__name__)

# UDL has historically used a few different field names across endpoints
# and sources. Accept any of these for the identifying columns.
_ID_KEYS = ("id", "idElset", "elsetId")
_SAT_NO_KEYS = ("satNo", "sat_no", "noradCatId", "noradId")
_EPOCH_KEYS = ("epoch", "epochDate", "epochTime")


@dataclass
class IngestResult:
    pulled: int
    inserted: int
    updated: int
    skipped: int


UDL_TO_MODEL_FIELDS: dict[str, str] = {
    "satNo": "sat_no",
    "epoch": "epoch",
    "meanMotion": "mean_motion",
    "eccentricity": "eccentricity",
    "inclination": "inclination",
    "raan": "raan",
    "argOfPerigee": "arg_of_perigee",
    "meanAnomaly": "mean_anomaly",
    "revNo": "rev_no",
    "bstar": "bstar",
    "meanMotionDot": "mean_motion_dot",
    "meanMotionDDot": "mean_motion_ddot",
    "semiMajorAxis": "semi_major_axis",
    "period": "period",
    "apogee": "apogee",
    "perigee": "perigee",
    "line1": "line1",
    "line2": "line2",
    "classificationMarking": "classification_marking",
    "dataMode": "data_mode",
    "source": "source",
}

UPDATABLE_COLUMNS: list[str] = [
    "sat_no",
    "epoch",
    "mean_motion",
    "eccentricity",
    "inclination",
    "raan",
    "arg_of_perigee",
    "mean_anomaly",
    "rev_no",
    "bstar",
    "mean_motion_dot",
    "mean_motion_ddot",
    "semi_major_axis",
    "period",
    "apogee",
    "perigee",
    "line1",
    "line2",
    "classification_marking",
    "data_mode",
    "source",
    "raw",
]


def _parse_epoch(value: str) -> datetime:
    # UDL often emits trailing Z (Zulu / UTC). fromisoformat() didn't
    # accept that on Python < 3.11; we normalise it for safety.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first_present(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_udl_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    udl_id = _first_present(record, _ID_KEYS)
    sat_no_raw = _first_present(record, _SAT_NO_KEYS)
    epoch_raw = _first_present(record, _EPOCH_KEYS)

    sat_no = _coerce_int(sat_no_raw) if sat_no_raw is not None else None

    if not udl_id or sat_no is None or not epoch_raw:
        # Diagnostic: tell the operator what we saw so we can extend
        # the field-name set if UDL is using something new. Sampled at
        # WARNING; let the caller decide how often to surface this.
        logger.warning(
            "Skipping UDL elset record: id=%r sat_no=%r epoch=%r keys=%s",
            udl_id,
            sat_no_raw,
            epoch_raw,
            sorted(record.keys()),
        )
        return None

    mapped: dict[str, Any] = {
        "udl_id": str(udl_id),
        "sat_no": sat_no,
        "raw": record,
    }
    if isinstance(epoch_raw, str):
        try:
            mapped["epoch"] = _parse_epoch(epoch_raw)
        except ValueError:
            logger.warning("Could not parse elset epoch %r; skipping", epoch_raw)
            return None
    elif isinstance(epoch_raw, datetime):
        mapped["epoch"] = epoch_raw
    else:
        logger.warning("Unexpected elset epoch type %s; skipping", type(epoch_raw))
        return None

    for udl_field, model_field in UDL_TO_MODEL_FIELDS.items():
        if udl_field in ("satNo", "epoch"):
            continue  # already populated above with the tolerant lookup
        if udl_field not in record:
            continue
        mapped[model_field] = record[udl_field]
    return mapped


async def ingest_elsets(
    db: AsyncSession,
    client: UDLClient,
    epoch_gte: datetime,
    sat_no: Optional[int] = None,
    data_mode: Optional[str] = None,
    max_results: Optional[int] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
) -> IngestResult:
    records = await client.get_elsets(
        epoch_gte=epoch_gte,
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
        # SQLAlchemy requires every row in a multi-row VALUES clause to
        # share the same column set. UDL elset records can vary (e.g.
        # some omit bstar or mean_motion_ddot), so backfill missing keys
        # with None before compiling.
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.keys())
        for r in rows:
            for key in all_keys:
                r.setdefault(key, None)

        existing_result = await db.execute(
            select(Elset.udl_id).where(Elset.udl_id.in_([r["udl_id"] for r in rows]))
        )
        existing_ids = {row[0] for row in existing_result.all()}

        stmt = pg_insert(Elset).values(rows)
        update_cols: dict[str, Any] = {
            col: getattr(stmt.excluded, col) for col in UPDATABLE_COLUMNS
        }
        update_cols["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            constraint="uq_elset_udl_id",
            set_=update_cols,
        )
        await db.execute(stmt)

        inserted = sum(1 for r in rows if r["udl_id"] not in existing_ids)
        updated = sum(1 for r in rows if r["udl_id"] in existing_ids)

    result = IngestResult(
        pulled=len(records),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
    )

    await write_audit(
        db,
        action_type="udl.elset.ingest",
        entity_type="elset_ingest_run",
        user_id=user_id,
        ip_address=ip_address,
        detail={
            "epoch_gte": epoch_gte.isoformat(),
            "sat_no": sat_no,
            "max_results": max_results,
            "pulled": result.pulled,
            "inserted": result.inserted,
            "updated": result.updated,
            "skipped": result.skipped,
        },
    )
    await db.commit()

    return result
