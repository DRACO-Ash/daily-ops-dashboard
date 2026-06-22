"""Pull configured Mattermost channels and upsert their posts.

Strategy per channel:
1. Find the most recent `posted_at` we already have for that channel.
2. Ask Mattermost for posts since (high-water mark - 1ms), or since
   `now - window` on the first run.
3. Upsert by `mm_post_id`; duplicates are ignored.
4. System messages (type starts with `system_`) are skipped.

User display names are looked up once per ingest cycle and cached in
a dict to avoid hitting `/users/{id}` for every message in a burst.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.mattermost_message import MattermostMessage
from app.services.audit import write_audit
from app.services.mattermost_client import (
    MattermostAuthError,
    MattermostClient,
    MattermostClientError,
    datetime_to_ms,
    ms_to_datetime,
)

logger = logging.getLogger(__name__)


@dataclass
class MattermostIngestResult:
    channels_polled: int
    channels_failed: int
    pulled: int
    inserted: int
    skipped: int


def _configured_channel_ids() -> list[str]:
    raw = settings.mattermost_channel_ids or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


async def _user_display_name(
    client: MattermostClient,
    user_id: str,
    cache: dict[str, Optional[str]],
) -> Optional[str]:
    if user_id in cache:
        return cache[user_id]
    try:
        user = await client.get_user(user_id)
        name = user.get("nickname") or user.get("username") or None
    except MattermostClientError:
        name = None
    cache[user_id] = name
    return name


async def _channel_name(
    client: MattermostClient,
    channel_id: str,
    cache: dict[str, Optional[str]],
) -> Optional[str]:
    if channel_id in cache:
        return cache[channel_id]
    try:
        channel = await client.get_channel(channel_id)
        name = channel.get("display_name") or channel.get("name") or None
    except MattermostClientError:
        name = None
    cache[channel_id] = name
    return name


async def _channel_high_water(db: AsyncSession, channel_id: str) -> Optional[datetime]:
    stmt = select(func.max(MattermostMessage.posted_at)).where(
        MattermostMessage.channel_id == channel_id
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    return result


async def ingest_mattermost_messages(
    db: AsyncSession,
    *,
    channel_ids: Optional[list[str]] = None,
    user_id_actor: Optional[Any] = None,
    ip_address: Optional[str] = None,
) -> MattermostIngestResult:
    channels = channel_ids if channel_ids is not None else _configured_channel_ids()
    if not channels:
        return MattermostIngestResult(0, 0, 0, 0, 0)

    fallback_since = datetime.now(timezone.utc) - timedelta(hours=24)
    user_cache: dict[str, Optional[str]] = {}
    channel_name_cache: dict[str, Optional[str]] = {}

    channels_polled = 0
    channels_failed = 0
    pulled = 0
    inserted = 0
    skipped = 0

    try:
        async with MattermostClient() as client:
            for channel_id in channels:
                high_water = await _channel_high_water(db, channel_id)
                since = high_water or fallback_since
                # Add 1ms padding so we don't re-pull the same boundary post.
                since_ms = datetime_to_ms(since) + (1 if high_water else 0)
                try:
                    payload = await client.get_channel_posts_since(channel_id, since_ms)
                except MattermostAuthError as exc:
                    logger.warning("Mattermost channel %s skipped: %s", channel_id, exc)
                    channels_failed += 1
                    continue
                except MattermostClientError as exc:
                    logger.warning("Mattermost channel %s failed: %s", channel_id, exc)
                    channels_failed += 1
                    continue

                channels_polled += 1
                posts: dict[str, dict[str, Any]] = payload.get("posts") or {}
                order: list[str] = payload.get("order") or []
                pulled += len(order)
                if not order:
                    continue

                channel_display_name = await _channel_name(client, channel_id, channel_name_cache)

                rows: list[dict[str, Any]] = []
                for post_id in order:
                    post = posts.get(post_id) or {}
                    post_type = post.get("type") or ""
                    if post_type.startswith("system_"):
                        skipped += 1
                        continue
                    create_at_ms = post.get("create_at")
                    if not isinstance(create_at_ms, int):
                        skipped += 1
                        continue
                    msg_text = post.get("message") or ""
                    if not msg_text.strip():
                        skipped += 1
                        continue
                    user_id = post.get("user_id") or ""
                    display = await _user_display_name(client, user_id, user_cache)
                    rows.append(
                        {
                            "mm_post_id": post.get("id"),
                            "channel_id": channel_id,
                            "channel_name": channel_display_name,
                            "user_id": user_id,
                            "user_display_name": display,
                            "posted_at": ms_to_datetime(create_at_ms),
                            "message": msg_text,
                            "post_type": post_type or None,
                            "raw": post,
                        }
                    )

                if not rows:
                    continue

                stmt = pg_insert(MattermostMessage).values(rows)
                stmt = stmt.on_conflict_do_nothing(constraint="uq_mattermost_message_post_id")
                result = await db.execute(stmt)
                inserted += result.rowcount or 0
    except MattermostClientError as exc:
        logger.warning("Mattermost ingest aborted: %s", exc)
        channels_failed = len(channels) - channels_polled

    summary = MattermostIngestResult(
        channels_polled=channels_polled,
        channels_failed=channels_failed,
        pulled=pulled,
        inserted=inserted,
        skipped=skipped,
    )

    if channels_polled or channels_failed:
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
                "skipped": summary.skipped,
            },
        )
        await db.commit()

    return summary
