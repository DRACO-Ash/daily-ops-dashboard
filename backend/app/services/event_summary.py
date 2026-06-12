"""Claude-driven 3-sentence narrative of how a single logical event evolved.

A "logical event" here is the dedup grouping used everywhere else: every
UDL re-publication of the same notice shares a group key (event_id /
notso_identifier / udl_id). This service feeds every publication of one
event to Claude in chronological order and asks for a strict 3-sentence
summary of the evolution.

Stored in event_summary keyed on event_key so the dashboard can render
the narrative without re-billing Claude on every load.
"""

import logging
from typing import Any, Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event_summary import EventSummary
from app.models.notification import Notification
from app.services.assistant import AssistantError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are summarising the evolution of a single space-operations event
across multiple UDL publications.

You will receive a chronological list of publications that all
reference the same logical event. Each publication is the operator
community's snapshot of the event at that moment.

Write a STRICT 3-sentence maximum paragraph in plain operational
English that tells the reader how the event evolved: what happened
first, what changed across publications, what the current status is.

Rules:
- HARD CAP: no more than 3 sentences.
- Plain text only. No markdown, no bullet list, no headings.
- Operational tone — name the satellite(s), event class, key timing.
- If only one publication exists, just describe that publication in
  at most 3 sentences.
- Do not quote the source publications.
"""


def compute_event_key(n: Notification) -> str:
    """Python mirror of the SQL COALESCE in notification_query.

    The SQL uses COALESCE(event_id, notso_identifier, udl_id) for the
    dedup grouping. We compute the same key in Python so the auto
    summariser can look up notifications by group and the dashboard
    can join notifications to their summary by key.
    """
    for value in (n.event_id, n.notso_identifier, n.udl_id):
        if value:
            return str(value)
    return str(n.id)


def _format_publication(index: int, n: Notification) -> str:
    parts = [f"Publication {index + 1}"]
    if n.udl_created_at:
        parts.append(f"udl_created={n.udl_created_at.isoformat()}")
    if n.status:
        parts.append(f"status={n.status}")
    if n.event_type:
        parts.append(f"event_type={n.event_type}")
    head = " | ".join(parts)

    body_lines = []
    if n.event_class:
        body_lines.append(f"  event_class: {n.event_class}")
    if n.subject and n.subject != n.event_class:
        body_lines.append(f"  subject: {n.subject}")
    if n.region:
        body_lines.append(f"  region: {n.region}")
    if n.sat_no is not None:
        body_lines.append(f"  sat_no: {n.sat_no}")
    if n.sat_ids:
        body_lines.append(f"  sat_ids: {', '.join(n.sat_ids)}")
    if n.description:
        body_lines.append(f"  description: {n.description.strip()}")
    if n.effective_from:
        body_lines.append(f"  effective_from: {n.effective_from.isoformat()}")
    if n.effective_until:
        body_lines.append(f"  effective_until: {n.effective_until.isoformat()}")

    return head + "\n" + "\n".join(body_lines)


def _build_user_message(publications: list[Notification]) -> str:
    blocks = [_format_publication(i, p) for i, p in enumerate(publications)]
    return "EVENT PUBLICATIONS (oldest to newest):\n\n" + "\n\n".join(blocks)


async def _call_claude(user_message: str) -> tuple[str, str]:
    if not settings.anthropic_api_key:
        raise AssistantError("ANTHROPIC_API_KEY is not configured")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=400,  # 3 sentences fits comfortably under 400 tokens
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        raise AssistantError(f"Anthropic API error: {exc}") from exc
    chunks: list[str] = []
    for block in response.content:
        text_value = getattr(block, "text", None)
        if isinstance(text_value, str):
            chunks.append(text_value)
    if not chunks:
        raise AssistantError("Model response contained no text blocks")
    return "\n".join(chunks).strip(), settings.anthropic_model


def _enforce_three_sentences(text: str) -> str:
    """Belt-and-braces: trim the narrative to its first three sentences
    if Claude over-shoots the cap."""
    import re

    pieces = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(pieces[:3]).strip()


async def generate_event_summary(
    db: AsyncSession,
    event_key: str,
    publications: list[Notification],
) -> EventSummary:
    """Generate or update the event summary for a logical event.

    Caller passes the publications already grouped + sorted chronologically.
    The row is upserted on event_key, so re-runs replace the prior text.
    """
    if not publications:
        raise AssistantError("Cannot summarise an empty publication list")

    publications = sorted(
        publications,
        key=lambda n: n.udl_created_at or n.created_at,
    )
    latest = publications[-1]

    error: Optional[str] = None
    narrative: str
    model: str
    try:
        narrative, model = await _call_claude(_build_user_message(publications))
        narrative = _enforce_three_sentences(narrative)
    except AssistantError as exc:
        logger.warning("Event summary failed for %s: %s", event_key, exc)
        error = str(exc)
        narrative = "Event summary could not be generated."
        model = settings.anthropic_model

    values: dict[str, Any] = {
        "event_key": event_key,
        "narrative": narrative,
        "source_notification_ids": [str(p.id) for p in publications],
        "latest_notification_id": latest.id,
        "publication_count": len(publications),
        "model": model,
        "error": error,
    }
    stmt = pg_insert(EventSummary).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_event_summary_event_key",
        set_={
            "narrative": stmt.excluded.narrative,
            "source_notification_ids": stmt.excluded.source_notification_ids,
            "latest_notification_id": stmt.excluded.latest_notification_id,
            "publication_count": stmt.excluded.publication_count,
            "model": stmt.excluded.model,
            "error": stmt.excluded.error,
        },
    )
    await db.execute(stmt)

    fetched = (
        await db.execute(select(EventSummary).where(EventSummary.event_key == event_key))
    ).scalar_one()
    return fetched
