"""Run saved Mattermost asks: targeted pulls instead of archiving everything.

An ask (schemas.mattermost.AskSpec) becomes a Mattermost team search:
terms and phrases, `from:` authors, `in:` channels and a date window,
optionally across archived channels. An ask naming only channels walks
those channels' history instead, since there is nothing to search for.

Mattermost search stems and prefix-matches words, so every candidate is
re-checked locally against the literal terms before it counts. Matching
posts are archived like any other pulled post, then shaped:

● posts: every match.
● thread_starts: one row per thread containing a match, for its first post.
● first_per_thread: one row per thread, for its earliest match.

Every row carries its thread: id, title (first line of the first post)
and start time. An optional pattern extracts one value per row, e.g. a
thread ID from the title.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mattermost_ask import MattermostAsk, MattermostAskResult
from app.schemas.mattermost import AskSpec
from app.services.audit import write_audit
from app.services.mattermost_client import (
    PER_PAGE,
    SEARCH_PER_PAGE,
    MattermostClient,
    MattermostClientError,
    ms_to_datetime,
)
from app.services.mattermost_ingest import (
    Channel,
    Cycle,
    channel_from_api,
    is_ingestible,
    page_posts,
    resolve_names,
    store_posts,
    team_id,
)

logger = logging.getLogger(__name__)

MAX_EXTRACT_INPUT = 2000  # characters a pattern may run over (see AskExtract)
EXCERPT_LENGTH = 500
TITLE_LENGTH = 300
_MARKDOWN_NOISE = re.compile(r"^[#>*_\s-]+|[*_`]+")


# Search -------------------------------------------------------------------------


def _quote(term: str) -> str:
    return f'"{term}"' if re.search(r"\s", term) else term


def build_search(spec: AskSpec) -> tuple[str, bool]:
    """Mattermost search string and is_or_search flag for `spec`.

    Mattermost applies one AND-or-OR mode to every word, so the server
    search uses the required terms when there are any (and `any_terms`
    are enforced locally), otherwise the any-terms as an OR search.
    Mattermost's `after:` and `before:` are exclusive, so the inclusive
    dates in the spec widen by a day each side.
    """
    words = spec.terms or spec.any_terms
    parts = [_quote(t) for t in words]
    parts += [f"from:{a.lstrip('@')}" for a in spec.authors]
    parts += [f"in:{c.lstrip('~')}" for c in spec.channels]
    if spec.after:
        parts.append(f"after:{(spec.after - timedelta(days=1)).isoformat()}")
    if spec.before:
        parts.append(f"before:{(spec.before + timedelta(days=1)).isoformat()}")
    return " ".join(parts), not spec.terms and len(spec.any_terms) > 1


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def in_window(post: dict[str, Any], spec: AskSpec) -> bool:
    posted = ms_to_datetime(post["create_at"])
    if spec.after and posted < _day_start(spec.after):
        return False
    return not (spec.before and posted >= _day_start(spec.before + timedelta(days=1)))


def matches_terms(message: str, spec: AskSpec) -> bool:
    """Literal, case-insensitive check: every term, and one any-term."""
    text = message.casefold()
    if not all(term.casefold() in text for term in spec.terms):
        return False
    return not spec.any_terms or any(term.casefold() in text for term in spec.any_terms)


@dataclass
class _Run:
    """One execution of one ask."""

    spec: AskSpec
    cycle: Cycle
    team_id: str
    partial: bool = False
    channels: dict[str, Channel] = field(default_factory=dict)
    posts: dict[str, dict[str, Any]] = field(default_factory=dict)


def _keep(run: _Run, post: dict[str, Any]) -> bool:
    """Authors need no re-check: Mattermost's `from:` is exact."""
    if not is_ingestible(post) or post.get("delete_at"):
        return False
    return in_window(post, run.spec) and matches_terms(post.get("message") or "", run.spec)


async def _resolve_targets(run: _Run) -> None:
    """Fail loudly on an unknown author or channel.

    Mattermost search quietly returns nothing for a misspelt `from:` or
    `in:`, which would read as "no results" rather than "wrong name".
    """
    if run.spec.authors:
        wanted = {a.lstrip("@").casefold(): a for a in run.spec.authors}
        users = await run.cycle.client.get_users_by_usernames(list(wanted))
        missing = set(wanted) - {str(u.get("username", "")).casefold() for u in users}
        if missing:
            names = ", ".join(sorted(wanted[m] for m in missing))
            raise MattermostClientError(f"Unknown Mattermost username: {names}")
    for name in run.spec.channels:
        try:
            raw = await run.cycle.client.get_channel_by_name(run.team_id, name.lstrip("~"))
        except MattermostClientError as exc:
            raise MattermostClientError(f"Unknown channel: {name}") from exc
        run.channels[str(raw["id"])] = channel_from_api(raw)


async def _search_candidates(run: _Run) -> list[dict[str, Any]]:
    terms, is_or = build_search(run.spec)
    found: list[dict[str, Any]] = []
    for page in range(settings.mattermost_ask_max_pages):
        payload = await run.cycle.client.search_team_posts(
            run.team_id,
            terms,
            is_or_search=is_or,
            include_archived=run.spec.include_archived,
            page=page,
        )
        batch = page_posts(payload)
        found.extend(batch)
        if len(payload.get("order") or []) < SEARCH_PER_PAGE:
            return found
    run.partial = True
    return found


async def _history_candidates(run: _Run) -> list[dict[str, Any]]:
    """Walk each named channel backwards until older than `after`."""
    found: list[dict[str, Any]] = []
    for channel in list(run.channels.values()):
        if channel.archived and not run.spec.include_archived:
            continue
        found.extend(await _walk_channel(run, channel.id))
    return found


async def _walk_channel(run: _Run, channel_id: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    floor = _day_start(run.spec.after) if run.spec.after else None
    for _ in range(settings.mattermost_ask_max_pages):
        payload = await run.cycle.client.get_channel_posts_before(channel_id, cursor)
        batch = page_posts(payload)
        found.extend(batch)
        if len(payload.get("order") or []) < PER_PAGE or not batch:
            return found
        if floor and ms_to_datetime(batch[-1]["create_at"]) < floor:
            return found
        cursor = str(batch[-1]["id"])
        await run.cycle.client.pause()
    run.partial = True
    return found


async def _candidates(run: _Run) -> list[dict[str, Any]]:
    if run.spec.terms or run.spec.any_terms or run.spec.authors:
        return await _search_candidates(run)
    return await _history_candidates(run)


# Threads and channels -----------------------------------------------------------


def thread_title(message: str) -> str:
    """First non-blank line with markdown emphasis and heading marks removed."""
    for line in message.splitlines():
        cleaned = _MARKDOWN_NOISE.sub("", line).strip()
        if cleaned:
            return cleaned[:TITLE_LENGTH]
    return ""


def thread_id_of(post: dict[str, Any]) -> str:
    return str(post.get("root_id") or post["id"])


async def _thread_roots(run: _Run, posts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    roots: dict[str, dict[str, Any]] = {p["id"]: p for p in posts if not p.get("root_id")}
    for root_id in sorted({thread_id_of(p) for p in posts} - set(roots)):
        try:
            roots[root_id] = await run.cycle.client.get_post(root_id)
        except MattermostClientError as exc:
            logger.info("Thread root %s unavailable: %s", root_id, exc)
    return roots


async def _channel(run: _Run, channel_id: str) -> Channel:
    if channel_id not in run.channels:
        try:
            run.channels[channel_id] = channel_from_api(
                await run.cycle.client.get_channel(channel_id)
            )
        except MattermostClientError:
            run.channels[channel_id] = Channel(id=channel_id, name=None)
    return run.channels[channel_id]


# Shaping --------------------------------------------------------------------------


def shape(spec: AskSpec, matches: list[dict[str, Any]], roots: dict[str, dict[str, Any]]) -> list:
    """Apply the spec's scope. Returns posts oldest first."""
    ordered = sorted(matches, key=lambda p: (p["create_at"], p["id"]))
    if spec.scope == "posts":
        return ordered
    by_thread: dict[str, dict[str, Any]] = {}
    for post in ordered:
        by_thread.setdefault(thread_id_of(post), post)
    if spec.scope == "first_per_thread":
        return list(by_thread.values())
    starts = [roots[t] for t in by_thread if t in roots]
    return sorted(starts, key=lambda p: (p["create_at"], p["id"]))


def extract(spec: AskSpec, message: str, title: str) -> Optional[str]:
    if spec.extract is None:
        return None
    source = title if spec.extract.source == "thread_title" else message
    found = re.search(spec.extract.pattern, source[:MAX_EXTRACT_INPUT])
    if found is None:
        return None
    return found.group(1) if found.re.groups else found.group(0)


def permalink(post_id: str) -> Optional[str]:
    if not (settings.mattermost_url and settings.mattermost_team):
        return None
    return f"{settings.mattermost_url.rstrip('/')}/{settings.mattermost_team}/pl/{post_id}"


def _result_row(
    run: _Run, post: dict[str, Any], roots: dict[str, dict[str, Any]], channel: Channel
) -> dict[str, Any]:
    root = roots.get(thread_id_of(post))
    title = thread_title(root.get("message") or "") if root else ""
    message = post.get("message") or ""
    return {
        "mm_post_id": post["id"],
        "channel_id": channel.id,
        "channel_name": channel.name,
        "channel_archived": channel.archived,
        "thread_id": thread_id_of(post),
        "thread_title": title or None,
        "thread_started_at": ms_to_datetime(root["create_at"]) if root else None,
        "author": run.cycle.names.get(post.get("user_id") or ""),
        "posted_at": ms_to_datetime(post["create_at"]),
        "extracted": extract(run.spec, message, title),
        "excerpt": message[:EXCERPT_LENGTH],
        "permalink": permalink(post["id"]),
    }


async def _archive(run: _Run, posts: list[dict[str, Any]]) -> None:
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in posts:
        by_channel[str(post.get("channel_id") or "")].append(post)
    for channel_id, channel_posts in by_channel.items():
        await store_posts(run.cycle, await _channel(run, channel_id), channel_posts)


# Execution --------------------------------------------------------------------------


async def _execute(run: _Run) -> list[dict[str, Any]]:
    await _resolve_targets(run)
    candidates = await _candidates(run)
    matches = [p for p in candidates if _keep(run, p)]
    await resolve_names(run.cycle, matches)
    roots = await _thread_roots(run, matches)
    await resolve_names(run.cycle, list(roots.values()))
    selected = shape(run.spec, matches, roots)
    await _archive(run, selected)
    return [
        _result_row(run, post, roots, await _channel(run, str(post.get("channel_id") or "")))
        for post in selected
    ]


async def _replace_results(db: AsyncSession, ask: MattermostAsk, rows: list[dict]) -> None:
    await db.execute(delete(MattermostAskResult).where(MattermostAskResult.ask_id == ask.id))
    if rows:
        await db.execute(
            pg_insert(MattermostAskResult).values([{**row, "ask_id": ask.id} for row in rows])
        )


def _reschedule(ask: MattermostAsk, now: datetime) -> None:
    ask.last_run_at = now
    ask.next_run_at = now + timedelta(minutes=ask.refresh_minutes) if ask.refresh_minutes else None


async def run_ask(db: AsyncSession, client: MattermostClient, ask: MattermostAsk) -> None:
    """Run one ask and store its results. Failures are recorded on the ask."""
    now = datetime.now(timezone.utc)
    spec = AskSpec.model_validate(ask.spec)
    cycle = Cycle(db=db, client=client)
    try:
        run = _Run(spec=spec, cycle=cycle, team_id=await team_id(client))
        rows = await _execute(run)
    except MattermostClientError as exc:
        ask.last_status, ask.last_error = "failed", str(exc)
        _reschedule(ask, now)
        await _audit_run(db, ask, cycle, None)
        return
    await _replace_results(db, ask, rows)
    ask.result_count = len(rows)
    ask.last_status = "partial" if run.partial else "ok"
    ask.last_error = (
        f"Stopped after {settings.mattermost_ask_max_pages} pages; narrow the ask."
        if run.partial
        else None
    )
    _reschedule(ask, now)
    await _audit_run(db, ask, cycle, len(rows))


async def _audit_run(
    db: AsyncSession, ask: MattermostAsk, cycle: Cycle, results: Optional[int]
) -> None:
    await write_audit(
        db,
        action_type="mattermost.ask.run",
        entity_type="mattermost_ask",
        entity_id=str(ask.id),
        detail={
            "status": ask.last_status,
            "results": results,
            "pulled": cycle.tally.pulled,
            "inserted": cycle.tally.inserted,
            "updated": cycle.tally.updated,
        },
    )


async def run_due_asks(db: AsyncSession) -> int:
    """Run every ask whose next_run_at has passed. Returns asks run."""
    now = datetime.now(timezone.utc)
    asks = list(
        (
            await db.execute(
                select(MattermostAsk)
                .where(MattermostAsk.next_run_at.is_not(None), MattermostAsk.next_run_at <= now)
                .order_by(MattermostAsk.next_run_at)
            )
        )
        .scalars()
        .all()
    )
    if not asks:
        return 0
    try:
        async with MattermostClient() as client:
            for ask in asks:
                await run_ask(db, client, ask)
                await db.commit()
    except MattermostClientError as exc:
        logger.warning("Mattermost asks aborted: %s", exc)
        for ask in asks:
            if ask.last_run_at is None or ask.last_run_at < now:
                ask.last_status, ask.last_error = "failed", str(exc)
                _reschedule(ask, now)
        await db.commit()
    return len(asks)
