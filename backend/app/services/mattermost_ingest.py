"""Pull Mattermost channels into a local archive.

Channels: `MATTERMOST_CHANNEL_IDS` if set, otherwise every open or
private channel the bot (dok.bot) belongs to in `MATTERMOST_TEAM`.

Per channel, each cycle:
1. Incremental: ask for posts created or modified since the channel's
   watermark (the highest `update_at` stored). New posts insert; edits
   replace the stored text only when newer; deletions set `deleted_at`
   and keep the last known text (archive, never delete).
2. Backfill: until the whole history is stored, walk backwards from the
   oldest post reached, up to `MATTERMOST_BACKFILL_PAGES_PER_CYCLE`
   pages. The first cycle for a channel therefore takes the full history.

System messages and blank posts are skipped. Author names are looked up
in batches and cached for the cycle.

Ported from the standalone `mattermost_channel_pull` tool.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func, literal_column, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mattermost_message import MattermostChannelState, MattermostMessage
from app.services.audit import write_audit
from app.services.mattermost_client import (
    PER_PAGE,
    MattermostAuthError,
    MattermostClient,
    MattermostClientError,
    ms_to_datetime,
)

logger = logging.getLogger(__name__)

# O is public, P is private. D and G (direct and group messages) are not
# team channels and are never ingested.
PULLABLE_TYPES = ("O", "P")


@dataclass
class MattermostIngestResult:
    channels_polled: int
    channels_failed: int
    pulled: int
    inserted: int
    skipped: int
    updated: int = 0
    deleted: int = 0


@dataclass
class _Tally:
    channels_polled: int = 0
    channels_failed: int = 0
    pulled: int = 0
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0

    def result(self) -> MattermostIngestResult:
        return MattermostIngestResult(
            channels_polled=self.channels_polled,
            channels_failed=self.channels_failed,
            pulled=self.pulled,
            inserted=self.inserted,
            skipped=self.skipped,
            updated=self.updated,
            deleted=self.deleted,
        )


@dataclass
class _Channel:
    id: str
    name: Optional[str]


@dataclass
class _Cycle:
    """Everything one ingest cycle shares across channels."""

    db: AsyncSession
    client: MattermostClient
    tally: _Tally = field(default_factory=_Tally)
    names: dict[str, Optional[str]] = field(default_factory=dict)


def _configured_channel_ids() -> list[str]:
    raw = settings.mattermost_channel_ids or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def selectable_channels(channels: list[dict[str, Any]]) -> list[_Channel]:
    """Open and private team channels that are not archived."""
    return [
        _Channel(id=str(c["id"]), name=c.get("display_name") or c.get("name") or None)
        for c in channels
        if c.get("id") and c.get("type") in PULLABLE_TYPES and not c.get("delete_at")
    ]


async def _channel_name(client: MattermostClient, channel_id: str) -> Optional[str]:
    try:
        channel = await client.get_channel(channel_id)
    except MattermostClientError:
        return None
    return channel.get("display_name") or channel.get("name") or None


async def _resolve_channels(client: MattermostClient) -> list[_Channel]:
    configured = _configured_channel_ids()
    if configured:
        return [_Channel(id=cid, name=await _channel_name(client, cid)) for cid in configured]
    # _is_configured() guarantees a team id or name when no ids are set.
    team_id = settings.mattermost_team_id or await client.get_team_id(settings.mattermost_team)
    return selectable_channels(await client.get_my_team_channels(team_id))


def _is_ingestible(post: dict[str, Any]) -> bool:
    """Skip system messages, posts without a timestamp, and blank posts."""
    if (post.get("type") or "").startswith("system_"):
        return False
    if not isinstance(post.get("create_at"), int):
        return False
    return bool((post.get("message") or "").strip())


def _is_deleted(post: dict[str, Any]) -> bool:
    return bool(post.get("delete_at"))


def _page_posts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Posts in the page's `order` (newest first), dropping dangling ids."""
    posts: dict[str, dict[str, Any]] = payload.get("posts") or {}
    order: list[str] = payload.get("order") or []
    return [posts[pid] for pid in order if isinstance(posts.get(pid), dict)]


def _ms_or_none(value: Any) -> Optional[Any]:
    return ms_to_datetime(value) if isinstance(value, int) and value > 0 else None


def _post_row(channel: _Channel, post: dict[str, Any], names: dict[str, Optional[str]]) -> dict:
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


async def _resolve_names(cycle: _Cycle, posts: list[dict[str, Any]]) -> None:
    unknown = sorted({p.get("user_id") or "" for p in posts} - set(cycle.names) - {""})
    if not unknown:
        return
    for user in await cycle.client.get_users_by_ids(unknown):
        cycle.names[str(user.get("id"))] = user.get("nickname") or user.get("username") or None
    for user_id in unknown:
        cycle.names.setdefault(user_id, None)


async def _upsert(cycle: _Cycle, channel: _Channel, posts: list[dict[str, Any]]) -> None:
    """Insert new posts; replace stored ones only with a newer revision."""
    await _resolve_names(cycle, posts)
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


async def _mark_deleted(cycle: _Cycle, posts: list[dict[str, Any]]) -> None:
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


async def _store(cycle: _Cycle, channel: _Channel, posts: list[dict[str, Any]]) -> None:
    cycle.tally.pulled += len(posts)
    deleted = [p for p in posts if _is_deleted(p)]
    live = [p for p in posts if not _is_deleted(p) and _is_ingestible(p)]
    cycle.tally.skipped += len(posts) - len(deleted) - len(live)
    if live:
        await _upsert(cycle, channel, live)
    if deleted:
        await _mark_deleted(cycle, deleted)


def _highest_update(posts: list[dict[str, Any]], current: int) -> int:
    stamps = [p.get("update_at") or p.get("create_at") or 0 for p in posts]
    return max([current, *[s for s in stamps if isinstance(s, int)]])


async def _load_state(db: AsyncSession, channel: _Channel) -> MattermostChannelState:
    state = await db.get(MattermostChannelState, channel.id)
    if state is None:
        state = MattermostChannelState(
            channel_id=channel.id, watermark_ms=0, backfill_complete=False
        )
        db.add(state)
    state.channel_name = channel.name
    return state


async def _pull_incremental(
    cycle: _Cycle, channel: _Channel, state: MattermostChannelState
) -> None:
    if not state.watermark_ms:
        return
    # `since` is exclusive; step back 1ms so a post revised in the same
    # millisecond as the watermark is not missed. The upsert ignores the
    # re-pulled revision it already holds.
    payload = await cycle.client.get_channel_posts_since(channel.id, state.watermark_ms - 1)
    posts = _page_posts(payload)
    await _store(cycle, channel, posts)
    state.watermark_ms = _highest_update(posts, state.watermark_ms)


async def _pull_backfill(cycle: _Cycle, channel: _Channel, state: MattermostChannelState) -> None:
    for _ in range(max(1, settings.mattermost_backfill_pages_per_cycle)):
        if state.backfill_complete:
            return
        payload = await cycle.client.get_channel_posts_before(channel.id, state.backfill_cursor)
        posts = _page_posts(payload)
        await _store(cycle, channel, posts)
        state.watermark_ms = _highest_update(posts, state.watermark_ms)
        if posts:
            state.backfill_cursor = str(posts[-1].get("id"))
        if len(payload.get("order") or []) < PER_PAGE:
            state.backfill_complete = True
            return
        await cycle.client.pause()


async def _ingest_channel(cycle: _Cycle, channel: _Channel) -> None:
    state = await _load_state(cycle.db, channel)
    try:
        await _pull_incremental(cycle, channel, state)
        await _pull_backfill(cycle, channel, state)
    except MattermostAuthError as exc:
        logger.warning("Mattermost channel %s skipped: %s", channel.id, exc)
        cycle.tally.channels_failed += 1
        return
    except MattermostClientError as exc:
        logger.warning("Mattermost channel %s failed: %s", channel.id, exc)
        cycle.tally.channels_failed += 1
        return
    cycle.tally.channels_polled += 1


async def _run_cycle(db: AsyncSession, channel_ids: Optional[list[str]]) -> _Tally:
    tally = _Tally()
    try:
        async with MattermostClient() as client:
            cycle = _Cycle(db=db, client=client, tally=tally)
            channels = (
                [_Channel(id=cid, name=await _channel_name(client, cid)) for cid in channel_ids]
                if channel_ids is not None
                else await _resolve_channels(client)
            )
            for channel in channels:
                await _ingest_channel(cycle, channel)
    except MattermostClientError as exc:
        logger.warning("Mattermost ingest aborted: %s", exc)
        tally.channels_failed += 1
    return tally


def _is_configured() -> bool:
    return bool(
        settings.mattermost_channel_ids or settings.mattermost_team or settings.mattermost_team_id
    )


async def ingest_mattermost_messages(
    db: AsyncSession,
    *,
    channel_ids: Optional[list[str]] = None,
    user_id_actor: Optional[Any] = None,
    ip_address: Optional[str] = None,
) -> MattermostIngestResult:
    if channel_ids == [] or (channel_ids is None and not _is_configured()):
        return MattermostIngestResult(0, 0, 0, 0, 0)

    summary = (await _run_cycle(db, channel_ids)).result()

    if summary.channels_polled or summary.channels_failed:
        await write_audit(
            db,
            action_type="mattermost.ingest",
            entity_type="mattermost_ingest_run",
            user_id=user_id_actor,
            ip_address=ip_address,
            detail={
                "channels_polled": summary.channels_polled,
                "channels_failed": summary.channels_failed,
                "pulled": summary.pulled,
                "inserted": summary.inserted,
                "updated": summary.updated,
                "deleted": summary.deleted,
                "skipped": summary.skipped,
            },
        )
    await db.commit()
    return summary
