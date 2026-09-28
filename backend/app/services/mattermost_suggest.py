"""Draft an ask spec from a plain-English question, for a human to review.

Only the question and the bot's channel names are sent to the model; no
Mattermost posts are. The draft is never saved or run here: the operator
edits and saves it. Output is validated against AskSpec, and one retry
feeds the validation error back to the model.

The pinned SDK predates native structured outputs, and forced tool
choice is rejected by the newest models, so JSON comes from the prompt
and is checked by pydantic instead.
"""

import json
from typing import Any

import anthropic
from anthropic.types import MessageParam
from pydantic import ValidationError

from app.config import settings
from app.schemas.mattermost import AskSuggestion
from app.services.assistant import AssistantError, _extract_json

_SYSTEM_PROMPT = """\
You turn an analyst's question about Mattermost chat into a search \
definition for a space domain awareness operations dashboard. Reply with \
one JSON object and nothing else:

{"name": str, "explanation": str, "spec": {
  "terms": [str],       // every one must appear (literal, case-insensitive)
  "any_terms": [str],   // at least one must appear, when given
  "authors": [str],     // Mattermost usernames, e.g. "michael.sellick"
  "channels": [str],    // channel URL names; empty means all channels
  "after": "YYYY-MM-DD" | null, "before": "YYYY-MM-DD" | null,
  "include_archived": bool,  // true searches archived channels as well
  "scope": "posts" | "thread_starts" | "first_per_thread",
  "extract": {"pattern": str, "source": "message" | "thread_title"} | null
}}

Rules:
- scope "thread_starts" returns the first post of each matching thread \
(when a thread started, its title). "first_per_thread" returns the \
earliest matching post in each thread (e.g. when something first \
happened in each thread). "posts" returns every matching post.
- Keep a satellite or object name together as one term, e.g. \
"COSMOS 2589". Put topic words that may vary in any_terms and include \
common synonyms, e.g. photometric: photometric, photometry, brightness, \
magnitude, light curve, flare, glint.
- extract.pattern is a Python regular expression with at most one \
capture group; the group's text is kept. Use it only when the question \
asks for a value inside the text, e.g. an ID in a thread title.
- Mattermost usernames are lowercase and usually firstname.lastname. \
When the question names a person or account and you are unsure of the \
username, give your best guess and say in the explanation that it must \
be checked.
- Only use channel names from the list provided; otherwise leave \
channels empty.
- "Open and closed" channels means include_archived true.
- explanation: two or three plain sentences an analyst can check.
"""


class SuggestError(Exception):
    """Raised when no valid suggestion could be produced."""


def _user_message(question: str, channels: list[str]) -> str:
    listing = ", ".join(sorted(channels)) if channels else "(unavailable)"
    return f"Channels the bot can see: {listing}\n\nQuestion: {question}"


def _response_text(response: Any) -> str:
    if response.stop_reason == "refusal":
        raise SuggestError("The model declined to draft this ask")
    if response.stop_reason == "max_tokens":
        raise SuggestError("The draft was cut off; raise ANTHROPIC_MAX_TOKENS")
    texts = [getattr(b, "text", None) for b in response.content]
    text = "\n".join(t for t in texts if isinstance(t, str))
    if not text:
        raise SuggestError("The model returned no text")
    return text


def _parse(text: str) -> AskSuggestion:
    try:
        return AskSuggestion.model_validate(_extract_json(text))
    except AssistantError as exc:
        raise SuggestError(str(exc)) from exc


async def _complete(client: anthropic.AsyncAnthropic, messages: list[MessageParam]) -> str:
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
    except anthropic.APIError as exc:
        raise SuggestError(f"Anthropic API error: {exc}") from exc
    return _response_text(response)


async def suggest_ask(question: str, channels: list[str]) -> AskSuggestion:
    """Draft an ask. One retry, with the validation error fed back."""
    if not settings.anthropic_api_key:
        raise SuggestError("ANTHROPIC_API_KEY is not configured")
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    messages: list[MessageParam] = [{"role": "user", "content": _user_message(question, channels)}]
    text = await _complete(client, messages)
    try:
        return _parse(text)
    except (SuggestError, ValidationError) as exc:
        feedback = json.dumps(str(exc))[:1500]
    messages += [
        {"role": "assistant", "content": text},
        {
            "role": "user",
            "content": f"That did not validate: {feedback}. "
            "Reply with the corrected JSON object only.",
        },
    ]
    retry = await _complete(client, messages)
    try:
        return _parse(retry)
    except (SuggestError, ValidationError) as exc:
        raise SuggestError(f"The draft was not a valid ask: {exc}") from exc
