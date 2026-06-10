import hashlib
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.procedure import Procedure
from app.models.user import User
from app.schemas.procedure import ProcedureContent, ProcedurePage, ProcedureRead
from app.services.audit import write_audit
from app.services.procedure_storage import (
    delete_file,
    read_file_bytes,
    read_preview,
    write_file,
)

router = APIRouter(prefix="/procedures", tags=["procedures"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("", response_model=ProcedurePage)
async def list_procedures(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ProcedurePage:
    stmt = select(Procedure).order_by(Procedure.created_at.desc())
    items = (await db.execute(stmt)).scalars().all()
    total = (await db.execute(select(sa_func.count()).select_from(Procedure))).scalar_one()
    return ProcedurePage(
        items=[ProcedureRead.model_validate(p) for p in items],
        total=total,
    )


@router.get("/{procedure_id}", response_model=ProcedureContent)
async def get_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> ProcedureContent:
    procedure = (
        await db.execute(select(Procedure).where(Procedure.id == procedure_id))
    ).scalar_one_or_none()
    if procedure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Procedure not found")
    content, truncated = read_preview(procedure.id, procedure.filename, procedure.content_type)
    return ProcedureContent(
        **ProcedureRead.model_validate(procedure).model_dump(),
        content=content,
        content_truncated=truncated,
    )


@router.get("/{procedure_id}/download")
async def download_procedure(
    procedure_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    procedure = (
        await db.execute(select(Procedure).where(Procedure.id == procedure_id))
    ).scalar_one_or_none()
    if procedure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Procedure not found")
    data = read_file_bytes(procedure.id, procedure.filename)

    def iterator():
        yield data

    return StreamingResponse(
        iterator(),
        media_type=procedure.content_type,
        headers={"Content-Disposition": f'attachment; filename="{procedure.filename}"'},
    )


@router.post("", response_model=ProcedureRead, status_code=status.HTTP_201_CREATED)
async def upload_procedure(
    request: Request,
    name: str = Form(...),
    description: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProcedureRead:
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
        )

    filename = file.filename or "procedure"
    file_hash = hashlib.sha256(data).hexdigest()

    procedure = Procedure(
        name=name.strip(),
        description=description.strip() if description else None,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        file_hash=file_hash,
        uploaded_by=current_user.id,
    )
    write_file(procedure.id, filename, data)
    db.add(procedure)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        delete_file(procedure.id, filename)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A procedure with identical content already exists",
        ) from None

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="procedure.upload",
        entity_type="procedure",
        entity_id=str(procedure.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "name": procedure.name,
            "filename": procedure.filename,
            "size_bytes": procedure.size_bytes,
        },
    )
    await db.commit()
    await db.refresh(procedure)
    return ProcedureRead.model_validate(procedure)


@router.delete("/{procedure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_procedure(
    procedure_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    procedure = (
        await db.execute(select(Procedure).where(Procedure.id == procedure_id))
    ).scalar_one_or_none()
    if procedure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Procedure not found")

    delete_file(procedure.id, procedure.filename)
    await db.delete(procedure)

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="procedure.delete",
        entity_type="procedure",
        entity_id=str(procedure.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={"name": procedure.name, "filename": procedure.filename},
    )
    await db.commit()
