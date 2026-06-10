"""Periodic background refresh of UDL data and Claude evaluations.

Runs the same ingest paths as the manual /ingest endpoints but on a
fixed cadence over a rolling window (default last 48 hours). When
auto-evaluate is enabled it then walks every notification in the
window that has no assistant evaluation yet and runs the reasoning
pipeline so the operator never has to click anything to see the
recommended next steps.

Lives outside the request lifecycle: opens its own AsyncSession per
phase, and swallows exceptions so a transient UDL or model outage
never kills the loop.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.db.session import get_session_factory
from app.models.assistant_evaluation import AssistantEvaluation
from app.models.notification import Notification
from app.services.assistant import evaluate_notification, is_persistent_anthropic_failure
from app.services.elset_ingest import ingest_elsets
from app.services.notification_ingest import ingest_notifications
from app.services.udl_client import UDLAuthError, UDLClient, UDLClientError

logger = logging.getLogger(__name__)


async def _ingest_phase() -> None:
    window_hours = settings.background_refresh_window_hours
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
            async with factory() as db:
                await ingest_elsets(
                    db,
                    client=client,
                    epoch_gte=window_start,
                )
        logger.info("Background ingest complete (window: last %sh)", window_hours)
    except UDLAuthError as exc:
        logger.warning("Background ingest skipped: UDL auth failed (%s)", exc)
    except UDLClientError as exc:
        logger.warning("Background ingest failed: %s", exc)
    except Exception:
        logger.exception("Background ingest crashed unexpectedly")


async def _auto_evaluate_phase() -> None:
    if not settings.background_auto_evaluate:
        return
    factory = get_session_factory()
    window_start = datetime.now(timezone.utc) - timedelta(
        hours=settings.background_refresh_window_hours
    )
    limit = settings.background_max_evaluations_per_cycle

    async with factory() as db:
        stmt = (
            select(Notification.id)
            .outerjoin(
                AssistantEvaluation,
                AssistantEvaluation.notification_id == Notification.id,
            )
            .where(AssistantEvaluation.id.is_(None))
            .where(Notification.udl_created_at >= window_start)
            .order_by(Notification.udl_created_at.desc())
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
        # If the evaluation persisted with a persistent-failure error
        # (credits exhausted, auth, rate limit), every remaining call
        # this cycle will hit the same wall; abort and wait for the
        # operator to resolve the underlying issue.
        if evaluation.error and is_persistent_anthropic_failure(evaluation.error):
            logger.warning("Stopping auto-evaluate cycle early: %s", evaluation.error)
            return


async def _refresh_once() -> None:
    await _ingest_phase()
    await _auto_evaluate_phase()


async def background_refresh_loop() -> None:
    if not settings.background_refresh_enabled:
        logger.info("Background refresh disabled via BACKGROUND_REFRESH_ENABLED")
        return
    logger.info(
        "Background refresh enabled: every %ss over last %sh, "
        "auto-evaluate=%s (max %s per cycle)",
        settings.background_refresh_interval_seconds,
        settings.background_refresh_window_hours,
        settings.background_auto_evaluate,
        settings.background_max_evaluations_per_cycle,
    )
    while True:
        try:
            await _refresh_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background refresh cycle crashed (continuing)")
        await asyncio.sleep(settings.background_refresh_interval_seconds)
