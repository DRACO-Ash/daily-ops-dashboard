"""Claude-driven reasoning over notifications, procedures, and orbital events.

Loads a notification plus all uploaded procedures, hands them to Claude
along with a strict JSON-output instruction, parses the structured
response, and persists it to the `assistant_evaluation` table.

Phase 2 Slice 1C: notifications + procedures only.
Slice 2 will add SGP4-derived orbital events to the prompt.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import anthropic
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.maneuver import Maneuver
from app.models.notification import Notification
from app.models.procedure import Procedure
from app.services.procedure_storage import read_preview

_MANEUVER_LOOKBACK_DAYS = 30
_MANEUVER_MAX_PER_PROMPT = 10

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an expert space operations analyst supporting a Daily Space
Operations team. You assist the operator by reading UDL notifications
(NOTSOs / TACREPs) alongside related maneuver records from fusion
providers and the team's own uploaded operational procedures, then
recommending concrete next steps.

Maneuver records describe historical or in-progress thrust events for
the same satellites referenced in the notification. Use them to spot
patterns (e.g. recent maneuver may explain a new conjunction) and to
contextualise the notification.

You must respond with a single JSON object and nothing else. No prose
before or after the JSON. Use this schema exactly:

{
  "summary": "One short paragraph in plain operational English. What
              is happening, who/what is involved, when.",
  "applicable_procedures": [
    {
      "procedure_id": "<the id provided>",
      "name": "<procedure name>",
      "reason": "Why this procedure applies to this notification"
    }
  ],
  "next_actions": [
    {
      "action": "Imperative description of what the operator should do",
      "urgency": "high" | "medium" | "low",
      "deadline": "ISO 8601 timestamp or null",
      "rationale": "Why; cite the procedure step or orbital trigger"
    }
  ],
  "open_questions": [
    "Question the operator must answer using judgement or external info"
  ]
}

Rules:
- Be specific. "Release a NOTSO" is weak; "Release follow-up NOTSO
  referencing this event 24h before re-entry" is good.
- Empty arrays are fine. If no procedure applies, return
  applicable_procedures: [].
- Do not invent procedure ids. Use only the ids supplied in the prompt.
- If the notification is informational only and no action is required,
  say so in summary and return next_actions: [].
- Use UTC for any timestamps.
"""


class AssistantError(Exception):
    """Raised when Claude returns an unparseable or invalid response."""


def _format_notification(n: Notification) -> str:
    lines = ["NOTIFICATION:"]
    if n.notso_identifier:
        lines.append(f"  Notice: {n.notso_identifier}")
    if n.msg_type:
        lines.append(f"  Message type: {n.msg_type}")
    if n.event_type:
        lines.append(f"  Event type: {n.event_type}")
    if n.event_class:
        lines.append(f"  Event class: {n.event_class}")
    if n.status:
        lines.append(f"  Status: {n.status}")
    if n.subject:
        lines.append(f"  Subject: {n.subject}")
    if n.description:
        lines.append(f"  Description: {n.description}")
    if n.region:
        lines.append(f"  Region: {n.region}")
    if n.company_name:
        lines.append(f"  Company: {n.company_name}")
    if n.publish_date:
        lines.append(f"  Published: {n.publish_date.isoformat()}")
    if n.effective_from:
        lines.append(f"  Effective from: {n.effective_from.isoformat()}")
    if n.effective_until:
        lines.append(f"  Effective until: {n.effective_until.isoformat()}")
    if n.udl_created_at:
        lines.append(f"  UDL created: {n.udl_created_at.isoformat()}")
    if n.sat_no is not None:
        lines.append(f"  Satellite: {n.sat_no}")
    if n.sat_ids:
        lines.append(f"  Satellites: {', '.join(n.sat_ids)}")
    if n.notso_link:
        lines.append(f"  Source link: {n.notso_link}")
    return "\n".join(lines)


def _format_maneuver(m: Maneuver) -> str:
    parts = [f"  - Sat {m.sat_no if m.sat_no is not None else '?'}"]
    if m.event_start_time:
        parts.append(f"start={m.event_start_time.isoformat()}")
    if m.event_stop_time:
        parts.append(f"stop={m.event_stop_time.isoformat()}")
    if m.mnvr_type:
        parts.append(f"type={m.mnvr_type}")
    if m.maneuver_status:
        parts.append(f"status={m.maneuver_status}")
    if m.delta_v is not None:
        parts.append(f"deltaV={m.delta_v}")
    if m.source:
        parts.append(f"source={m.source}")
    head = " | ".join(parts)
    if m.description:
        return f"{head}\n    {m.description.strip()}"
    return head


def _extract_sat_nos(notification: Notification) -> list[int]:
    nos: list[int] = []
    if notification.sat_no is not None:
        nos.append(notification.sat_no)
    if notification.sat_ids:
        for value in notification.sat_ids:
            try:
                nos.append(int(value))
            except (TypeError, ValueError):
                continue
    # de-duplicate, preserve order
    seen: set[int] = set()
    ordered: list[int] = []
    for n in nos:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


async def _load_relevant_maneuvers(db: AsyncSession, notification: Notification) -> list[Maneuver]:
    sat_nos = _extract_sat_nos(notification)
    if not sat_nos:
        return []
    window_start = datetime.now(timezone.utc) - timedelta(days=_MANEUVER_LOOKBACK_DAYS)
    stmt = (
        select(Maneuver)
        .where(Maneuver.sat_no.in_(sat_nos))
        .where(
            or_(
                Maneuver.event_start_time.is_(None),
                Maneuver.event_start_time >= window_start,
            )
        )
        .order_by(Maneuver.event_start_time.desc().nullslast())
        .limit(_MANEUVER_MAX_PER_PROMPT)
    )
    return list((await db.execute(stmt)).scalars().all())


def _format_procedure(p: Procedure) -> str:
    content, truncated = read_preview(p.id, p.filename, p.content_type)
    block = [
        f"PROCEDURE id={p.id} name={p.name!r}",
    ]
    if p.description:
        block.append(f"  Description: {p.description}")
    if content is None:
        block.append("  Content: <binary or unsupported preview type; operator should view file>")
    else:
        block.append("  Content:")
        block.append(content)
        if truncated:
            block.append("  ... (truncated)")
    return "\n".join(block)


def _build_user_message(
    notification: Notification,
    procedures: list[Procedure],
    maneuvers: list[Maneuver],
) -> str:
    parts = [_format_notification(notification), ""]
    if maneuvers:
        lines = [f"RELATED MANEUVERS (same satellite, last {_MANEUVER_LOOKBACK_DAYS} days):"]
        lines.extend(_format_maneuver(m) for m in maneuvers)
        parts.append("\n".join(lines))
    else:
        parts.append("RELATED MANEUVERS: (none for the satellite(s) in this notification)")
    if procedures:
        parts.append("AVAILABLE PROCEDURES:")
        parts.extend(_format_procedure(p) for p in procedures)
    else:
        parts.append("AVAILABLE PROCEDURES: (none uploaded)")
    parts.append("")
    parts.append("Return the JSON object as specified. No text before or after the JSON.")
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first balanced JSON object out of a model response.

    Walks the text character by character tracking brace depth, but
    skips characters inside string literals so a `{` or `}` appearing
    inside a quoted value (e.g. a procedure snippet Claude is citing)
    doesn't throw the counter off and produce a spurious "unterminated"
    error.
    """
    start = text.find("{")
    if start == -1:
        raise AssistantError("Model response contained no JSON object")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                payload = text[start : i + 1]
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise AssistantError(f"Model response was not valid JSON: {exc}") from exc
    raise AssistantError("Model response had an unterminated JSON object")


async def _call_claude(user_message: str) -> tuple[dict[str, Any], str]:
    if not settings.anthropic_api_key:
        raise AssistantError("ANTHROPIC_API_KEY is not configured")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        # Surface SDK errors (auth, credit, rate limit, server) as
        # AssistantError so evaluate_notification persists a row with
        # the failure reason rather than letting the exception escape.
        raise AssistantError(f"Anthropic API error: {exc}") from exc
    if response.stop_reason == "max_tokens":
        # Truncated mid-output; the JSON will be incomplete. Surface a
        # specific error rather than letting the parser fail later on
        # the half-written object with a cryptic "unterminated" message.
        raise AssistantError(
            f"Model response was truncated at {settings.anthropic_max_tokens} tokens "
            "before completing the JSON. Raise ANTHROPIC_MAX_TOKENS."
        )
    # response.content is list[TextBlock | ToolUseBlock]; only text
    # blocks expose .text. Use getattr so mypy is happy without a
    # cast or a hard isinstance import (the SDK's block class paths
    # are not part of its public API contract).
    blocks: list[str] = []
    for b in response.content:
        text_value = getattr(b, "text", None)
        if isinstance(text_value, str):
            blocks.append(text_value)
    if not blocks:
        raise AssistantError("Model response contained no text blocks")
    text = "\n".join(blocks)
    return _extract_json(text), settings.anthropic_model


def is_persistent_anthropic_failure(error_message: Optional[str]) -> bool:
    """True if the failure is unlikely to clear up within a poll cycle.

    Used by the background poller to break out of the auto-evaluate
    loop instead of burning the per-cycle quota against an outage that
    every call will hit identically.
    """
    if not error_message:
        return False
    lower = error_message.lower()
    return any(
        needle in lower
        for needle in (
            "credit balance",
            "rate limit",
            "authentication",
            "invalid api key",
            "permission",
        )
    )


async def evaluate_notification(
    db: AsyncSession,
    notification_id: Any,
) -> AssistantEvaluation:
    notification = (
        await db.execute(select(Notification).where(Notification.id == notification_id))
    ).scalar_one_or_none()
    if notification is None:
        raise AssistantError("Notification not found")

    procedures = (
        (await db.execute(select(Procedure).order_by(Procedure.created_at))).scalars().all()
    )
    maneuvers = await _load_relevant_maneuvers(db, notification)

    user_message = _build_user_message(notification, list(procedures), maneuvers)

    error: Optional[str] = None
    structured: dict[str, Any]
    model: str
    try:
        structured, model = await _call_claude(user_message)
    except AssistantError as exc:
        logger.warning("Assistant evaluation failed for %s: %s", notification_id, exc)
        error = str(exc)
        structured = {
            "summary": "Assistant evaluation could not be generated.",
            "applicable_procedures": [],
            "next_actions": [],
            "open_questions": [],
        }
        model = settings.anthropic_model

    summary = str(structured.get("summary", "")) or "No summary returned."

    evaluation = AssistantEvaluation(
        notification_id=notification.id,
        summary=summary,
        structured=structured,
        procedures_used=[str(p.id) for p in procedures],
        model=model,
        error=error,
    )
    db.add(evaluation)
    await db.flush()
    return evaluation


async def get_latest_evaluation(
    db: AsyncSession,
    notification_id: Any,
) -> Optional[AssistantEvaluation]:
    stmt = (
        select(AssistantEvaluation)
        .where(AssistantEvaluation.notification_id == notification_id)
        .order_by(AssistantEvaluation.evaluated_at.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()
