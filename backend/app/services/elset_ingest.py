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
    return datetime.fromisoformat(value)


def _map_udl_record(record: dict[str, Any]) -> Optional[dict[str, Any]]:
    udl_id = record.get("id")
    sat_no = record.get("satNo")
    epoch = record.get("epoch")
    if not udl_id or sat_no is None or not epoch:
        return None

    mapped: dict[str, Any] = {
        "udl_id": str(udl_id),
        "raw": record,
    }
    for udl_field, model_field in UDL_TO_MODEL_FIELDS.items():
        if udl_field not in record:
            continue
        value = record[udl_field]
        if udl_field == "epoch" and isinstance(value, str):
            value = _parse_epoch(value)
        mapped[model_field] = value
    return mapped


async def ingest_elsets(
    db: AsyncSession,
    client: UDLClient,
    epoch_gte: datetime,
    sat_no: Optional[int] = None,
    max_results: Optional[int] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
) -> IngestResult:
    records = await client.get_elsets(epoch_gte=epoch_gte, sat_no=sat_no, max_results=max_results)

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
