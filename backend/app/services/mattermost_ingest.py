"""Mattermost archive storage and on-demand full-history pulls.

Nothing is pulled continuously. Posts reach the archive in two ways:

● Asks (services/mattermost_asks.py) store the posts they match.
● A full-history job pulls every post from chosen channels (or all the
  bot's channels in MATTERMOST_TEAM) starting at a time the operator
  picks. Each background cycle walks each channel backwards from the
  oldest post reached, up to MATTERMOST_BACKFILL_PAGES_PER_CYCLE pages,
  so a large channel completes over several cycles.

Archive semantics, shared by both: edits replace the stored text only
when newer; deletions set `deleted_at` and keep the last known text.
Ported from the standalone `mattermost_channel_pull` tool.
"""

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mattermost_ask import MattermostHistoryJob
from app.models.mattermost_message import MattermostChannelState, MattermostMessage
from app.services.audit import write_audit
from app.services.mattermost_client import (
    PER_PAGE,
    MattermostClient,
    MattermostClientError,
    ms_to_datetime,
)

logger = logging.getLogger(__name__)

# O is public, P is private. D and G (direct and group messages) are not
# team channels and are never pulled.
PULLABLE_TYPES = ("O", "P")
ACTIVE_JOB_STATUSES = ("scheduled", "running")


@dataclass
class Tally:
    pulled: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0

    def add_to(self, counts: dict[str, int]) -> dict[str, int]:
        merged = dict(counts)
        for key, value in asdict(self).items():
            merged[key] = merged.get(key, 0) + value
        return merged


@dataclass
class Channel:
    id: str
    name: Optional[str]
    archived: bool = False


@dataclass
class Cycle:
    """State shared by one pass over Mattermost."""

    db: AsyncSession
    client: MattermostClient
    tally: Tally = field(default_factory=Tally)
    names: dict[str, Optional[str]] = field(default_factory=dict)


# Channels ---------------------------------------------------------------------


def channel_from_api(raw: dict[str, Any]) -> Channel:
    return Channel(
        id=str(raw["id"]),
        name=raw.get("display_name") or raw.get("name") or None,
        archived=bool(raw.get("delete_at")),
    )


def selectable_channels(channels: list[dict[str, Any]]) -> list[Channel]:
    """Open and private team channels that are not archived."""
    return [
        channel_from_api(c)
        for c in channels
        if c.get("id") and c.get("type") in PULLABLE_TYPES and not c.get("delete_at")
    ]


async def team_id(client: MattermostClient) -> str:
    if settings.mattermost_team_id:
        return settings.mattermost_team_id
    if not settings.mattermost_team:
        raise MattermostClientError("MATTERMOST_TEAM is not configured")
    return await client.get_team_id(settings.mattermost_team)


async def bot_channels(client: MattermostClient) -> list[Channel]:
    """Every live open or private channel the bot belongs to in the team."""
    return selectable_channels(await client.get_my_team_channels(await team_id(client)))


# Storage ----------------------------------------------------------------------


def is_ingestible(post: dict[str, Any]) -> bool:
    """Skip system messages, posts without a timestamp, and blank posts."""
    if (post.get("type") or "").startswith("system_"):
        return False
    if not isinstance(post.get("create_at"), int):
        return False
    return bool((post.get("message") or "").strip())


def _is_deleted(post: dict[str, Any]) -> bool:
    return bool(post.get("delete_at"))


def page_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Posts in the page's `order` (newest first), dropping dangling ids."""
    posts: dict[str, dict[str, Any]] = payload.get("posts") or {}
    order: list[str] = payload.get("order") or []
    return [posts[pid] for pid in order if isinstance(posts.get(pid), dict)]


def _ms_or_none(value: Any) -> Optional[datetime]:
    return ms_to_datetime(value) if isinstance(value, int) and value > 0 else None


def _post_row(channel: Channel, post: dict[str, Any], names: dict[str, Optional[str]]) -> dict:
    user_id = post.get("user_id") or ""
    return {
        "mm_post_id": post.get("id"),
        "channel_id": channel.id,
        "channel_name": channel.name,
        "user_id": user_id,
        "user_display_name": names.get(user_id),
        "posted_at": ms_to_datetime(post["create_at"]),
        "message": post.get("message") or "",
        "post_type": post.get("type") or None,
        "root_id": post.get("root_id") or None,
        "mm_updated_at": post.get("update_at") or post["create_at"],
        "edited_at": _ms_or_none(post.get("edit_at")),
        "raw": post,
    }


async def resolve_names(cycle: Cycle, posts: list[dict[str, Any]]) -> None:
    """Fill `cycle.names` for every author in `posts`, in batched lookups."""
    unknown = sorted({p.get("user_id") or "" for p in posts} - set(cycle.names) - {""})
    if not unknown:
        return
    for user in await cycle.client.get_users_by_ids(unknown):
        cycle.names[str(user.get("id"))] = user.get("nickname") or user.get("username") or None
    for user_id in unknown:
        cycle.names.setdefault(user_id, None)


async def _upsert(cycle: Cycle, channel: Channel, posts: list[dict[str, Any]]) -> None:
    """Insert new posts; replace stored ones only with a newer revision."""
    await resolve_names(cycle, posts)
    rows = [_post_row(channel, p, cycle.names) for p in posts]
    insert = pg_insert(MattermostMessage).values(rows)
    excluded = insert.excluded
    stmt: Any = insert.on_conflict_do_update(
        constraint="uq_mattermost_message_post_id",
        set_={
            "message": excluded.message,
            "edited_at": excluded.edited_at,
            "mm_updated_at": excluded.mm_updated_at,
            "raw": excluded.raw,
            "user_display_name": excluded.user_display_name,
            "channel_name": excluded.channel_name,
        },
        # Rows stored before revisions were tracked have no update_at.
        where=excluded.mm_updated_at > func.coalesce(MattermostMessage.mm_updated_at, 0),
    ).returning(literal_column("(xmax = 0)").label("inserted"))
    flags = (await cycle.db.execute(stmt)).scalars().all()
    inserted = sum(1 for flag in flags if flag)
    cycle.tally.inserted += inserted
    cycle.tally.updated += len(flags) - inserted


async def _mark_deleted(cycle: Cycle, posts: list[dict[str, Any]]) -> None:
    """Flag stored posts as deleted; the stored text is kept."""
    for post in posts:
        result = await cycle.db.execute(
            update(MattermostMessage)
            .where(
                MattermostMessage.mm_post_id == post.get("id"),
                MattermostMessage.deleted_at.is_(None),
            )
            .values(deleted_at=ms_to_datetime(post["delete_at"]), mm_updated_at=post["delete_at"])
        )
        cycle.tally.deleted += result.rowcount or 0


async def store_posts(cycle: Cycle, channel: Channel, posts: list[dict[str, Any]]) -> None:
    """Archive `posts` from one channel."""
    cycle.tally.pulled += len(posts)
    deleted = [p for p in posts if _is_deleted(p)]
    live = [p for p in posts if not _is_deleted(p) and is_ingestible(p)]
    cycle.tally.skipped += len(posts) - len(deleted) - len(live)
    if live:
        await _upsert(cycle, channel, live)
    if deleted:
        await _mark_deleted(cycle, deleted)


def _highest_update(posts: list[dict[str, Any]], current: int) -> int:
    stamps = [p.get("update_at") or p.get("create_at") or 0 for p in posts]
    return max([current, *[s for s in stamps if isinstance(s, int)]])


# Full-history jobs --------------------------------------------------------------


async def _load_state(db: AsyncSession, channel: Channel) -> MattermostChannelState:
    state = await db.get(MattermostChannelState, channel.id)
    if state is None:
        state = MattermostChannelState(
            channel_id=channel.id, watermark_ms=0, backfill_complete=False
        )
        db.add(state)
    if channel.name:
        state.channel_name = channel.name
    return state


async def _pull_history_pages(cycle: Cycle, channel: Channel) -> bool:
    """Advance one channel's history walk. Returns True once complete."""
    state = await _load_state(cycle.db, channel)
    for _ in range(max(1, settings.mattermost_backfill_pages_per_cycle)):
        if state.backfill_complete:
            return True
        payload = await cycle.client.get_channel_posts_before(channel.id, state.backfill_cursor)
        posts = page_posts(payload)
        await store_posts(cycle, channel, posts)
        state.watermark_ms = _highest_update(posts, state.watermark_ms)
        if posts:
            state.backfill_cursor = str(posts[-1].get("id"))
        if len(payload.get("order") or []) < PER_PAGE:
            state.backfill_complete = True
            return True
        await cycle.client.pause()
    return state.backfill_complete


async def _start_job(cycle: Cycle, job: MattermostHistoryJob) -> None:
    """Resolve the job's channels and restart their history walks."""
    if not job.channel_ids:
        job.channel_ids = [c.id for c in await bot_channels(cycle.client)]
    for channel_id in job.channel_ids:
        state = await _load_state(cycle.db, Channel(id=channel_id, name=None))
        state.backfill_complete = False
        state.backfill_cursor = None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    await write_audit(
        cycle.db,
        action_type="mattermost.history.start",
        entity_type="mattermost_history_job",
        entity_id=str(job.id),
        user_id=job.requested_by,
        detail={"channel_ids": job.channel_ids},
    )


async def _channel_names(cycle: Cycle, channel_ids: list[str]) -> dict[str, Optional[str]]:
    names: dict[str, Optional[str]] = {}
    for channel_id in channel_ids:
        try:
            raw = await cycle.client.get_channel(channel_id)
        except MattermostClientError:
            names[channel_id] = None
            continue
        names[channel_id] = channel_from_api(raw).name
    return names


async def _advance_job(cycle: Cycle, job: MattermostHistoryJob) -> bool:
    """One cycle of work on a running job. Returns True when finished."""
    pending = [c for c in job.channel_ids if c not in job.failed_channel_ids]
    names = await _channel_names(cycle, pending)
    finished = True
    for channel_id in pending:
        try:
            done = await _pull_history_pages(cycle, Channel(id=channel_id, name=names[channel_id]))
        except MattermostClientError as exc:
            logger.warning("History pull for channel %s failed: %s", channel_id, exc)
            job.failed_channel_ids = [*job.failed_channel_ids, channel_id]
            job.error = f"{channel_id}: {exc}"
            continue
        finished = finished and done
    return finished


async def _finish_job(cycle: Cycle, job: MattermostHistoryJob, status: str) -> None:
    job.status = status
    job.finished_at = datetime.now(timezone.utc)
    await write_audit(
        cycle.db,
        action_type="mattermost.history.finish",
        entity_type="mattermost_history_job",
        entity_id=str(job.id),
        user_id=job.requested_by,
        detail={
            "status": status,
            "counts": job.counts,
            "failed_channel_ids": job.failed_channel_ids,
        },
    )


async def _run_job(cycle: Cycle, job: MattermostHistoryJob) -> None:
    if job.status == "scheduled":
        await _start_job(cycle, job)
    cycle.tally = Tally()
    finished = await _advance_job(cycle, job)
    job.counts = cycle.tally.add_to(job.counts)
    if finished:
        all_failed = len(job.failed_channel_ids) == len(job.channel_ids) > 0
        await _finish_job(cycle, job, "failed" if all_failed else "done")


async def run_history_jobs(db: AsyncSession) -> int:
    """Advance every due history job by one cycle. Returns jobs touched."""
    now = datetime.now(timezone.utc)
    jobs = list(
        (
            await db.execute(
                select(MattermostHistoryJob)
                .where(
                    MattermostHistoryJob.status.in_(ACTIVE_JOB_STATUSES),
                    MattermostHistoryJob.run_after <= now,
                )
                .order_by(MattermostHistoryJob.run_after)
            )
        )
        .scalars()
        .all()
    )
    if not jobs:
        return 0
    try:
        async with MattermostClient() as client:
            for job in jobs:
                await _run_job(Cycle(db=db, client=client), job)
                await db.commit()
    except MattermostClientError as exc:
        # An HTTP-level failure (unconfigured, team not found) leaves the
        # session usable, so progress already made is kept.
        logger.warning("Mattermost history jobs aborted: %s", exc)
        for job in jobs:
            if job.status in ACTIVE_JOB_STATUSES:
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = datetime.now(timezone.utc)
        await db.commit()
    return len(jobs)
