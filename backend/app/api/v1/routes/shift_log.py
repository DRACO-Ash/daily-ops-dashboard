from datetime import date as date_t
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.shift_note import ShiftNote
from app.models.shift_summary import ShiftSummary
from app.models.user import User
from app.schemas.shift import (
    ShiftNoteCreate,
    ShiftNoteList,
    ShiftNoteRead,
    ShiftNoteUpdate,
    ShiftSummaryRead,
)
from app.services.audit import write_audit
from app.services.shift_log import polish_text, summarise_shift

router = APIRouter(prefix="/shift-log", tags=["shift-log"])


def _today_utc() -> date_t:
    return datetime.now(timezone.utc).date()


# Notes ----------------------------------------------------------


@router.get("/notes", response_model=ShiftNoteList)
async def list_notes(
    shift_date: Optional[date_t] = Query(None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ShiftNoteList:
    target = shift_date or _today_utc()
    stmt = (
        select(ShiftNote).where(ShiftNote.shift_date == target).order_by(ShiftNote.created_at.asc())
    )
    items = (await db.execute(stmt)).scalars().all()
    return ShiftNoteList(
        items=[ShiftNoteRead.model_validate(n) for n in items],
        shift_date=target,
    )


@router.post("/notes", response_model=ShiftNoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: ShiftNoteCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftNoteRead:
    raw = payload.raw_text.strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Note text cannot be empty.",
        )
    polished, model, error = await polish_text(raw)
    note = ShiftNote(
        author_id=current_user.id,
        shift_date=payload.shift_date or _today_utc(),
        raw_text=raw,
        polished_text=polished,
        polish_error=error,
        model=model,
    )
    db.add(note)
    await db.flush()

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="shift_log.note.create",
        entity_type="shift_note",
        entity_id=str(note.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "shift_date": note.shift_date.isoformat(),
            "had_error": error is not None,
        },
    )
    await db.commit()
    await db.refresh(note)
    return ShiftNoteRead.model_validate(note)


@router.patch("/notes/{note_id}", response_model=ShiftNoteRead)
async def update_note(
    note_id: UUID,
    payload: ShiftNoteUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftNoteRead:
    note = (await db.execute(select(ShiftNote).where(ShiftNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    if payload.polished_text is not None:
        note.polished_text = payload.polished_text.strip() or None
        note.polish_error = None
    await db.flush()

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="shift_log.note.update",
        entity_type="shift_note",
        entity_id=str(note.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={"shift_date": note.shift_date.isoformat()},
    )
    await db.commit()
    await db.refresh(note)
    return ShiftNoteRead.model_validate(note)


@router.post("/notes/{note_id}/repolish", response_model=ShiftNoteRead)
async def repolish_note(
    note_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftNoteRead:
    note = (await db.execute(select(ShiftNote).where(ShiftNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    polished, model, error = await polish_text(note.raw_text)
    note.polished_text = polished
    note.polish_error = error
    note.model = model
    await db.flush()

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="shift_log.note.repolish",
        entity_type="shift_note",
        entity_id=str(note.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={"had_error": error is not None},
    )
    await db.commit()
    await db.refresh(note)
    return ShiftNoteRead.model_validate(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    note = (await db.execute(select(ShiftNote).where(ShiftNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    shift_date = note.shift_date
    await db.delete(note)

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="shift_log.note.delete",
        entity_type="shift_note",
        entity_id=str(note_id),
        user_id=current_user.id,
        ip_address=ip,
        detail={"shift_date": shift_date.isoformat()},
    )
    await db.commit()


# Summary --------------------------------------------------------


@router.get("/summary", response_model=Optional[ShiftSummaryRead])
async def get_summary(
    shift_date: Optional[date_t] = Query(None),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Optional[ShiftSummaryRead]:
    target = shift_date or _today_utc()
    stmt = (
        select(ShiftSummary)
        .where(ShiftSummary.shift_date == target)
        .order_by(desc(ShiftSummary.created_at))
        .limit(1)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    return ShiftSummaryRead.model_validate(row)


@router.post("/summary", response_model=ShiftSummaryRead)
async def generate_summary(
    request: Request,
    shift_date: Optional[date_t] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ShiftSummaryRead:
    target = shift_date or _today_utc()
    notes = (
        (
            await db.execute(
                select(ShiftNote)
                .where(ShiftNote.shift_date == target)
                .order_by(ShiftNote.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not notes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No notes recorded for {target.isoformat()}.",
        )
    narrative, model, error = await summarise_shift(db, list(notes))
    summary = ShiftSummary(
        shift_date=target,
        generated_by=current_user.id,
        narrative=narrative or "Summary could not be generated.",
        source_note_ids=[str(n.id) for n in notes],
        model=model,
        error=error,
    )
    db.add(summary)
    await db.flush()

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="shift_log.summary.generate",
        entity_type="shift_summary",
        entity_id=str(summary.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "shift_date": target.isoformat(),
            "note_count": len(notes),
            "had_error": error is not None,
        },
    )
    await db.commit()
    await db.refresh(summary)
    return ShiftSummaryRead.model_validate(summary)


# Export ---------------------------------------------------------

_ExportFormat = Literal["md", "html"]


def _build_markdown(
    shift_date: date_t,
    notes: list[ShiftNote],
    summary: Optional[ShiftSummary],
) -> str:
    parts: list[str] = []
    parts.append(f"# Daily Operations Shift Log — {shift_date.isoformat()}")
    parts.append("")
    if summary is not None:
        parts.append("## End-of-shift narrative")
        parts.append("")
        parts.append(summary.narrative.strip())
        parts.append("")
    parts.append("## Timeline")
    parts.append("")
    for note in notes:
        ts = note.created_at.strftime("%Y-%m-%d %H:%M:%SZ") if note.created_at else "?"
        body = (note.polished_text or note.raw_text).strip()
        parts.append(f"**{ts}**")
        parts.append("")
        parts.append(body)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _build_html(
    shift_date: date_t,
    notes: list[ShiftNote],
    summary: Optional[ShiftSummary],
) -> str:
    def esc(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    style = """\
    body { font-family: 'Segoe UI', system-ui, sans-serif; max-width: 820px;
           margin: 40px auto; padding: 0 24px; color: #1f2937; line-height: 1.55; }
    h1 { font-weight: 300; font-size: 1.8rem; border-bottom: 2px solid #385FAF;
         padding-bottom: 8px; }
    h2 { color: #162646; margin-top: 32px; font-weight: 500; }
    .timeline-entry { margin-bottom: 18px; padding: 10px 14px;
                      border-left: 3px solid #385FAF; background: #f6f8fc; }
    .timeline-ts { font-size: 0.8rem; color: #6b7785; letter-spacing: 0.06em;
                   text-transform: uppercase; margin-bottom: 4px; }
    .narrative { padding: 16px; background: #f6f8fc; border-radius: 6px;
                 white-space: pre-wrap; }
    @media print {
      body { max-width: none; margin: 0; }
      .timeline-entry { page-break-inside: avoid; }
    }
    """
    body_parts: list[str] = [f"<h1>Daily Operations Shift Log — {esc(shift_date.isoformat())}</h1>"]
    if summary is not None:
        body_parts.append("<h2>End-of-shift narrative</h2>")
        body_parts.append(f'<div class="narrative">{esc(summary.narrative.strip())}</div>')
    body_parts.append("<h2>Timeline</h2>")
    for note in notes:
        ts = note.created_at.strftime("%Y-%m-%d %H:%M:%SZ") if note.created_at else "?"
        body = esc((note.polished_text or note.raw_text).strip())
        body_parts.append(
            f'<div class="timeline-entry">'
            f'<div class="timeline-ts">{esc(ts)}</div>'
            f"<div>{body}</div>"
            f"</div>"
        )
    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>"
        f"<title>Shift log {esc(shift_date.isoformat())}</title>"
        f"<style>{style}</style></head><body>" + "\n".join(body_parts) + "</body></html>"
    )


@router.get("/export", response_class=PlainTextResponse)
async def export_shift(
    shift_date: Optional[date_t] = Query(None),
    fmt: _ExportFormat = Query("md", alias="format"),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> PlainTextResponse:
    target = shift_date or _today_utc()
    notes = (
        (
            await db.execute(
                select(ShiftNote)
                .where(ShiftNote.shift_date == target)
                .order_by(ShiftNote.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    summary = (
        await db.execute(
            select(ShiftSummary)
            .where(ShiftSummary.shift_date == target)
            .order_by(desc(ShiftSummary.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    if fmt == "html":
        body = _build_html(target, list(notes), summary)
        return PlainTextResponse(
            content=body,
            media_type="text/html",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="shift-log-{target.isoformat()}.html"'
                )
            },
        )
    body = _build_markdown(target, list(notes), summary)
    return PlainTextResponse(
        content=body,
        media_type="text/markdown",
        headers={
            "Content-Disposition": (f'attachment; filename="shift-log-{target.isoformat()}.md"')
        },
    )
