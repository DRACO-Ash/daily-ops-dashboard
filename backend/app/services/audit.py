import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog

AUDIT_ADVISORY_LOCK_KEY = 0x4F505841


def _serialise_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_entry_hash(previous_hash: Optional[str], serialised_payload: str) -> str:
    chain_input = (previous_hash or "") + serialised_payload
    return hashlib.sha256(chain_input.encode("utf-8")).hexdigest()


async def write_audit(
    db: AsyncSession,
    *,
    action_type: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
) -> AuditLog:
    payload = {
        "action_type": action_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "user_id": str(user_id) if user_id is not None else None,
        "ip_address": ip_address,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    serialised = _serialise_payload(payload)

    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": AUDIT_ADVISORY_LOCK_KEY},
    )

    latest = await db.execute(
        select(AuditLog.entry_hash).order_by(AuditLog.timestamp.desc()).limit(1)
    )
    previous_hash = latest.scalar_one_or_none()

    entry_hash = _compute_entry_hash(previous_hash, serialised)
    entry = AuditLog(
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
        ip_address=ip_address,
        detail=json.dumps(detail, default=str) if detail is not None else None,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
    )
    db.add(entry)
    await db.flush()
    return entry
