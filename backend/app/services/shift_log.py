"""Claude-driven polish and end-of-shift narrative for the ops-floor log.

Two distinct prompts:

● polish: the operator types a raw observation (often a rant), Claude
  rewrites it as a professional, factual single paragraph stripped of
  opinion or controversy.

● summarise: at end-of-shift, Claude reads the day's polished notes in
  order and composes a handover narrative for the incoming crew.
"""

import logging
from typing import Optional

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.shift_note import ShiftNote
from app.services.assistant import AssistantError, is_persistent_anthropic_failure

logger = logging.getLogger(__name__)

_POLISH_SYSTEM_PROMPT = """\
You are an editor for a Daily Space Operations team's shift log.

The operator types raw observations from the ops floor. They may be
informal, opinionated, ranty, or contain controversy and blame.

Rewrite each input as a single short paragraph that:
● Preserves every operationally relevant fact (times, satellite
  numbers, event identifiers, named systems, actions taken, decisions
  made, people involved by role rather than by personal attack).
● Removes opinion, blame, sarcasm, profanity, and personal attacks.
● Reads as something appropriate for an end-of-shift log and any
  follow-on hand-over.

Return only the rewritten paragraph as plain text. No headings, no
"the operator said", no commentary on what you changed.
"""

_SUMMARY_SYSTEM_PROMPT = """\
You are writing the end-of-shift handover narrative for a Daily Space
Operations team.

You will receive a chronological list of polished shift notes from a
single shift. Produce a short markdown document with:

1. A single opening line that names the date and headlines the shift
   (e.g. "Quiet shift dominated by routine maneuver tracking" or
   "Multi-event shift led by a Soyuz launch and follow-on conjunction
   work").
2. 2-4 short narrative paragraphs telling the story of the shift in
   roughly chronological order, grouping related notes where it helps
   readability.
3. A final "**Handover items**" markdown bullet list of anything that
   is unresolved and needs the incoming shift's attention. If nothing
   is outstanding, write "**Handover items**: none.".

Plain markdown only. No HTML, no code fences, no preamble before
section 1.
"""


async def _async_call_claude_text(
    system_prompt: str,
    user_message: str,
    max_tokens: int,
) -> tuple[str, str]:
    if not settings.anthropic_api_key:
        raise AssistantError("ANTHROPIC_API_KEY is not configured")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            system=system_prompt,
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


async def polish_text(raw: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (polished_text, model, error).

    On success: (polished, model, None).
    On failure: (None, model, error_message). Caller is expected to
    persist the row anyway so the raw observation is not lost.
    """
    try:
        polished, model = await _async_call_claude_text(
            _POLISH_SYSTEM_PROMPT, raw.strip(), max_tokens=settings.anthropic_max_tokens
        )
    except AssistantError as exc:
        logger.warning("Shift-note polish failed: %s", exc)
        return None, settings.anthropic_model, str(exc)
    return polished, model, None


def _format_notes_for_summary(notes: list[ShiftNote]) -> str:
    lines: list[str] = []
    for n in notes:
        ts = n.created_at.isoformat() if n.created_at else "?"
        body = (n.polished_text or n.raw_text).strip()
        lines.append(f"- {ts}: {body}")
    return "\n".join(lines)


async def summarise_shift(
    db: AsyncSession,
    notes: list[ShiftNote],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (narrative_markdown, model, error)."""
    _ = db  # reserved for future cross-context lookups
    if not notes:
        return None, settings.anthropic_model, "Cannot summarise an empty shift."
    user_message = _format_notes_for_summary(notes)
    try:
        narrative, model = await _async_call_claude_text(
            _SUMMARY_SYSTEM_PROMPT,
            user_message,
            max_tokens=settings.anthropic_max_tokens,
        )
    except AssistantError as exc:
        logger.warning("Shift summary generation failed: %s", exc)
        return None, settings.anthropic_model, str(exc)
    return narrative, model, None


__all__ = [
    "polish_text",
    "summarise_shift",
    "is_persistent_anthropic_failure",
]
