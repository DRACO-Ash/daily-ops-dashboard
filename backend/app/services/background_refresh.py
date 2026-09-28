"""Per-surface background refresh loops.

Three independent asyncio tasks, each managing one external surface
with its own cadence:

● notifications — hourly, 5-day window from UDL. After each pull,
  runs the auto-evaluate phase (per-notification Claude analysis)
  and the event-summary phase (3-sentence evolution narrative per
  logical event).
● maneuvers — every 10 minutes, 48h window from UDL. Pull only.
● mattermost — every 60 seconds, runs only work an operator asked
  for: full-history jobs whose start time has passed, and saved asks
  that are due. Nothing is pulled continuously. Archived posts flow
  into the assistant prompt alongside notifications and maneuvers.

Elset auto-pulling was removed because the operator wasn't using
the data; the backend route/model/table remain for recoverability.

Each loop opens its own AsyncSession per phase and swallows
exceptions so a transient outage never kills it.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.config import settings
from app.db.session import get_session_factory
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.event_summary import EventSummary
from app.models.notification import Notification
from app.services.assistant import evaluate_notification, is_persistent_anthropic_failure
from app.services.event_summary import compute_event_key, generate_event_summary
from app.services.maneuver_ingest import ingest_maneuvers
from app.services.mattermost_asks import run_due_asks
from app.services.mattermost_ingest import run_history_jobs
from app.services.notification_ingest import ingest_notifications
from app.services.notification_query import aliased_deduped_notifications
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError

logger = logging.getLogger(__name__)


# Notifications -------------------------------------------------


async def _pull_notifications_once() -> None:
    window_hours = settings.background_notification_window_hours
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    factory = get_session_factory()
    try:
        async with UDLClient() as client:
            async with factory() as db:
                await ingest_notifications(
                    db,
                    client=client,
                    msg_type="TACREP_NOTSO",
                    created_at_gte=window_start,
                    data_mode="REAL",
                    source="JCO",
                )
        logger.info("Notification ingest complete (window: last %sh)", window_hours)
    except UDLAuthError as exc:
        logger.warning("Notification ingest skipped: UDL auth failed (%s)", exc)
    except UDLClientError as exc:
        logger.warning("Notification ingest failed: %s", exc)
    except Exception:
        logger.exception("Notification ingest crashed unexpectedly")


async def _auto_evaluate_phase() -> None:
    if not settings.background_auto_evaluate:
        return
    factory = get_session_factory()
    window_start = datetime.now(timezone.utc) - timedelta(
        hours=settings.background_notification_window_hours
    )
    limit = settings.background_max_evaluations_per_cycle

    async with factory() as db:
        # Only evaluate the latest version of each logical notice; UDL
        # re-publishes them, and we don't want to spend Claude tokens
        # on every duplicate.
        notif_alias, _dedup_subq = aliased_deduped_notifications(
            [Notification.udl_created_at >= window_start]
        )
        stmt = (
            select(notif_alias.id)
            .outerjoin(
                AssistantEvaluation,
                AssistantEvaluation.notification_id == notif_alias.id,
            )
            .where(AssistantEvaluation.id.is_(None))
            .order_by(notif_alias.udl_created_at.desc())
            .limit(limit)
        )
        ids = [row[0] for row in (await db.execute(stmt)).all()]

    if not ids:
        return
    logger.info("Auto-evaluating %s un-analysed notification(s)", len(ids))
    for notification_id in ids:
        async with factory() as db:
            try:
                evaluation = await evaluate_notification(db, notification_id)
                await db.commit()
            except Exception:
                logger.exception("Auto-evaluate failed for notification %s", notification_id)
                await db.rollback()
                continue
        if evaluation.error and is_persistent_anthropic_failure(evaluation.error):
            logger.warning("Stopping auto-evaluate cycle early: %s", evaluation.error)
            return


def _summary_is_stale(existing: Optional[EventSummary], pubs: list[Notification]) -> bool:
    """True if the event has no summary, or its summary predates the
    latest publication or covers a different number of publications."""
    if existing is None:
        return True
    latest = max(pubs, key=lambda p: p.udl_created_at or p.created_at)
    return existing.latest_notification_id != latest.id or existing.publication_count != len(pubs)


async def _event_summary_phase() -> None:
    """Refresh event-evolution summaries for any logical event whose
    latest publication is newer than its existing summary."""
    factory = get_session_factory()
    window_start = datetime.now(timezone.utc) - timedelta(
        hours=settings.background_notification_window_hours
    )
    limit = settings.background_max_event_summaries_per_cycle

    async with factory() as db:
        # Load all publications in the window. Grouping is done in
        # Python so we can compute the same COALESCE event_key the
        # rest of the system uses without a lateral join.
        publications = list(
            (
                await db.execute(
                    select(Notification)
                    .where(Notification.udl_created_at >= window_start)
                    .order_by(Notification.udl_created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    grouped: dict[str, list[Notification]] = defaultdict(list)
    for n in publications:
        grouped[compute_event_key(n)].append(n)

    if not grouped:
        return

    async with factory() as db:
        existing_rows = (
            (
                await db.execute(
                    select(EventSummary).where(EventSummary.event_key.in_(grouped.keys()))
                )
            )
            .scalars()
            .all()
        )
    existing_by_key = {row.event_key: row for row in existing_rows}

    stale_keys = [
        key for key, pubs in grouped.items() if _summary_is_stale(existing_by_key.get(key), pubs)
    ]

    if not stale_keys:
        return

    stale_keys = stale_keys[:limit]
    logger.info("Refreshing %s event summary/summaries", len(stale_keys))
    for key in stale_keys:
        if not await _refresh_event_summary(factory, key, grouped[key]):
            return


async def _refresh_event_summary(factory, key: str, pubs: list[Notification]) -> bool:
    """Regenerate one summary. Returns False to stop the cycle early."""
    async with factory() as db:
        try:
            summary = await generate_event_summary(db, key, pubs)
            await db.commit()
        except Exception:
            logger.exception("Event summary failed for %s", key)
            await db.rollback()
            return True
    if summary.error and is_persistent_anthropic_failure(summary.error):
        logger.warning("Stopping event summary cycle early: %s", summary.error)
        return False
    return True


async def _notification_cycle() -> None:
    await _pull_notifications_once()
    await _auto_evaluate_phase()
    await _event_summary_phase()


# Mattermost ------------------------------------------------------


async def _pull_mattermost_once() -> None:
    factory = get_session_factory()
    phases = (("history jobs", run_history_jobs), ("asks", run_due_asks))
    for name, phase in phases:
        try:
            async with factory() as db:
                await phase(db)
        except Exception:
            logger.exception("Mattermost %s crashed unexpectedly", name)


# Maneuvers ------------------------------------------------------


async def _pull_maneuvers_once() -> None:
    window_hours = settings.background_maneuver_window_hours
    window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    factory = get_session_factory()
    try:
        async with UDLClient() as client:
            async with factory() as db:
                await ingest_maneuvers(
                    db,
                    client=client,
                    event_start_time_gte=window_start,
                    data_mode="REAL",
                )
        logger.info("Maneuver ingest complete (window: last %sh)", window_hours)
    except UDLAuthError as exc:
        logger.warning("Maneuver ingest skipped: UDL auth failed (%s)", exc)
    except UDLClientError as exc:
        logger.warning("Maneuver ingest failed: %s", exc)
    except Exception:
        logger.exception("Maneuver ingest crashed unexpectedly")


# Loops ----------------------------------------------------------


def _make_loop(name: str, work, interval: int):
    async def _loop():
        logger.info(
            "Background %s loop enabled: every %ss",
            name,
            interval,
        )
        while True:
            try:
                await work()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background %s cycle crashed (continuing)", name)
            await asyncio.sleep(interval)

    return _loop


def notification_loop():
    return _make_loop(
        "notifications",
        _notification_cycle,
        settings.background_notification_interval_seconds,
    )()


def maneuver_loop():
    return _make_loop(
        "maneuvers",
        _pull_maneuvers_once,
        settings.background_maneuver_interval_seconds,
    )()


def mattermost_loop():
    return _make_loop(
        "mattermost",
        _pull_mattermost_once,
        settings.mattermost_interval_seconds,
    )()


async def run_pull_notifications_now() -> None:
    """Public entry point so an HTTP handler can trigger the notification
    pipeline on demand (without waiting for the hourly cadence)."""
    await _notification_cycle()
