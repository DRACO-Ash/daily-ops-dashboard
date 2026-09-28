"""Mattermost asks, on-demand full-history jobs, and their supporting lookups.

Reading is open to any signed-in user. Anything that pulls from
Mattermost, changes what will be pulled, or sends text to the model
needs the operator or admin role, and is audited.
"""

import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user, require_role
from app.models.mattermost_ask import MattermostAsk, MattermostAskResult, MattermostHistoryJob
from app.models.mattermost_message import MattermostChannelState
from app.models.user import User, UserRole
from app.schemas.mattermost import (
    AskCreate,
    AskRead,
    AskResultPage,
    AskResultRead,
    AskSuggestion,
    AskSuggestRequest,
    HistoryJobCreate,
    HistoryJobRead,
    MattermostChannelRead,
)
from app.services.audit import write_audit
from app.services.mattermost_client import MattermostClient, MattermostClientError
from app.services.mattermost_ingest import ACTIVE_JOB_STATUSES, PULLABLE_TYPES, team_id
from app.services.mattermost_suggest import SuggestError, suggest_ask

router = APIRouter(prefix="/mattermost", tags=["mattermost"])

_writer = require_role(UserRole.OPERATOR, UserRole.ADMIN)
_CSV_COLUMNS = (
    "posted_at",
    "channel_name",
    "channel_archived",
    "author",
    "thread_id",
    "thread_title",
    "thread_started_at",
    "extracted",
    "excerpt",
    "permalink",
    "mm_post_id",
)
# A spreadsheet treats a cell starting with one of these as a formula.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _bad_gateway(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


async def _get_ask(db: AsyncSession, ask_id: UUID) -> MattermostAsk:
    ask = await db.get(MattermostAsk, ask_id)
    if ask is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ask not found")
    return ask


async def _audit(
    db: AsyncSession, request: Request, user: User, action: str, entity: Any, detail: dict
) -> None:
    await write_audit(
        db,
        action_type=action,
        entity_type=entity.__tablename__,
        entity_id=str(entity.id),
        user_id=user.id,
        ip_address=_ip(request),
        detail=detail,
    )


# Channels and people ---------------------------------------------------------------


async def _live_channels() -> list[dict[str, Any]]:
    async with MattermostClient() as client:
        return await client.get_my_team_channels(await team_id(client))


@router.get("/channels", response_model=list[MattermostChannelRead])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[MattermostChannelRead]:
    """The bot's team channels, archived included, with history status."""
    try:
        raw = await _live_channels()
    except MattermostClientError as exc:
        raise _bad_gateway(exc) from exc
    states = {s.channel_id: s for s in (await db.execute(select(MattermostChannelState))).scalars()}
    channels = [
        MattermostChannelRead(
            id=str(c["id"]),
            name=str(c.get("name") or c["id"]),
            display_name=c.get("display_name") or None,
            type=str(c.get("type")),
            archived=bool(c.get("delete_at")),
            history_complete=bool(
                states.get(str(c["id"])) and states[str(c["id"])].backfill_complete
            ),
        )
        for c in raw
        if c.get("id") and c.get("type") in PULLABLE_TYPES
    ]
    return sorted(channels, key=lambda c: (c.archived, c.name))


@router.get("/users")
async def search_people(
    q: str = Query(..., min_length=2, max_length=100),
    _user: User = Depends(_writer),
) -> list[dict[str, Optional[str]]]:
    """Find a Mattermost username from a name, for an ask's authors."""
    try:
        async with MattermostClient() as client:
            found = await client.search_users(q, await team_id(client))
    except MattermostClientError as exc:
        raise _bad_gateway(exc) from exc
    return [
        {
            "username": u.get("username"),
            "name": " ".join(p for p in (u.get("first_name"), u.get("last_name")) if p) or None,
            "nickname": u.get("nickname") or None,
        }
        for u in found
    ]


# Asks -------------------------------------------------------------------------------


@router.get("/asks", response_model=list[AskRead])
async def list_asks(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[AskRead]:
    rows = (await db.execute(select(MattermostAsk).order_by(MattermostAsk.name))).scalars()
    return [AskRead.model_validate(a) for a in rows]


@router.post("/asks", response_model=AskRead, status_code=status.HTTP_201_CREATED)
async def create_ask(
    payload: AskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> AskRead:
    ask = MattermostAsk(
        name=payload.name.strip(),
        question=payload.question,
        spec=payload.spec.model_dump(mode="json"),
        refresh_minutes=payload.refresh_minutes,
        result_count=0,
        created_by=user.id,
    )
    db.add(ask)
    await db.flush()
    await _audit(
        db, request, user, "mattermost.ask.create", ask, {"name": ask.name, "spec": ask.spec}
    )
    await db.commit()
    await db.refresh(ask)
    return AskRead.model_validate(ask)


@router.get("/asks/{ask_id}", response_model=AskRead)
async def get_ask(
    ask_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AskRead:
    return AskRead.model_validate(await _get_ask(db, ask_id))


@router.put("/asks/{ask_id}", response_model=AskRead)
async def update_ask(
    ask_id: UUID,
    payload: AskCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> AskRead:
    ask = await _get_ask(db, ask_id)
    ask.name = payload.name.strip()
    ask.question = payload.question
    ask.spec = payload.spec.model_dump(mode="json")
    ask.refresh_minutes = payload.refresh_minutes
    await _audit(
        db, request, user, "mattermost.ask.update", ask, {"name": ask.name, "spec": ask.spec}
    )
    await db.commit()
    await db.refresh(ask)
    return AskRead.model_validate(ask)


@router.delete("/asks/{ask_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ask(
    ask_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> None:
    ask = await _get_ask(db, ask_id)
    await _audit(db, request, user, "mattermost.ask.delete", ask, {"name": ask.name})
    await db.delete(ask)
    await db.commit()


@router.post("/asks/{ask_id}/run", response_model=AskRead)
async def schedule_ask(
    ask_id: UUID,
    request: Request,
    run_at: Optional[datetime] = Query(None, description="Omit to run on the next cycle"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> AskRead:
    """Queue the ask. The background loop runs it within one cycle of `run_at`."""
    ask = await _get_ask(db, ask_id)
    when = run_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        raise HTTPException(status_code=422, detail="run_at must include a timezone")
    ask.next_run_at = when
    ask.last_status = "queued"
    await _audit(db, request, user, "mattermost.ask.schedule", ask, {"run_at": when.isoformat()})
    await db.commit()
    await db.refresh(ask)
    return AskRead.model_validate(ask)


@router.post("/asks/{ask_id}/unschedule", response_model=AskRead)
async def unschedule_ask(
    ask_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> AskRead:
    ask = await _get_ask(db, ask_id)
    ask.next_run_at = None
    await _audit(db, request, user, "mattermost.ask.unschedule", ask, {})
    await db.commit()
    await db.refresh(ask)
    return AskRead.model_validate(ask)


@router.get("/asks/{ask_id}/results", response_model=AskResultPage)
async def list_results(
    ask_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> AskResultPage:
    await _get_ask(db, ask_id)
    where = MattermostAskResult.ask_id == ask_id
    total = (
        await db.execute(select(sa_func.count()).select_from(MattermostAskResult).where(where))
    ).scalar_one()
    rows = (
        await db.execute(
            select(MattermostAskResult)
            .where(where)
            .order_by(MattermostAskResult.posted_at)
            .limit(limit)
            .offset(offset)
        )
    ).scalars()
    return AskResultPage(
        items=[AskResultRead.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def csv_cell(value: Any) -> str:
    """Render a value for CSV, neutralising spreadsheet formula injection."""
    if value is None:
        return ""
    text = value.isoformat() if isinstance(value, datetime) else str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def results_csv(rows: list[MattermostAskResult]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for row in rows:
        writer.writerow([csv_cell(getattr(row, column)) for column in _CSV_COLUMNS])
    return buffer.getvalue()


@router.get("/asks/{ask_id}/results.csv")
async def export_results(
    ask_id: UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StreamingResponse:
    ask = await _get_ask(db, ask_id)
    rows = list(
        (
            await db.execute(
                select(MattermostAskResult)
                .where(MattermostAskResult.ask_id == ask_id)
                .order_by(MattermostAskResult.posted_at)
            )
        ).scalars()
    )
    filename = "".join(c if c.isalnum() else "_" for c in ask.name)[:60] or "ask"
    return StreamingResponse(
        iter([results_csv(rows)]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.post("/asks/suggest", response_model=AskSuggestion)
async def suggest(
    payload: AskSuggestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> AskSuggestion:
    """Draft an ask from a question. Nothing is saved or run."""
    try:
        channels = [str(c.get("name")) for c in await _live_channels() if c.get("name")]
    except MattermostClientError:
        channels = []
    try:
        suggestion = await suggest_ask(payload.question, channels)
    except SuggestError as exc:
        raise _bad_gateway(exc) from exc
    await write_audit(
        db,
        action_type="mattermost.ask.suggest",
        entity_type="mattermost_ask",
        user_id=user.id,
        ip_address=_ip(request),
        detail={"question": payload.question},
    )
    await db.commit()
    return suggestion


# Full-history jobs -------------------------------------------------------------------


@router.get("/history-jobs", response_model=list[HistoryJobRead])
async def list_history_jobs(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[HistoryJobRead]:
    rows = (
        await db.execute(
            select(MattermostHistoryJob).order_by(MattermostHistoryJob.created_at.desc()).limit(50)
        )
    ).scalars()
    return [HistoryJobRead.model_validate(j) for j in rows]


@router.post("/history-jobs", response_model=HistoryJobRead, status_code=status.HTTP_201_CREATED)
async def create_history_job(
    payload: HistoryJobCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> HistoryJobRead:
    """Pull the full history of some or all channels at a chosen time."""
    run_after = payload.run_after or datetime.now(timezone.utc)
    if run_after.tzinfo is None:
        raise HTTPException(status_code=422, detail="run_after must include a timezone")
    job = MattermostHistoryJob(
        channel_ids=payload.channel_ids,
        run_after=run_after,
        status="scheduled",
        counts={},
        failed_channel_ids=[],
        requested_by=user.id,
    )
    db.add(job)
    await db.flush()
    await _audit(
        db,
        request,
        user,
        "mattermost.history.request",
        job,
        {"channel_ids": job.channel_ids, "run_after": run_after.isoformat()},
    )
    await db.commit()
    await db.refresh(job)
    return HistoryJobRead.model_validate(job)


@router.post("/history-jobs/{job_id}/cancel", response_model=HistoryJobRead)
async def cancel_history_job(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_writer),
) -> HistoryJobRead:
    job = await db.get(MattermostHistoryJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if job.status not in ACTIVE_JOB_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Job is {job.status}")
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    await _audit(db, request, user, "mattermost.history.cancel", job, {})
    await db.commit()
    await db.refresh(job)
    return HistoryJobRead.model_validate(job)
