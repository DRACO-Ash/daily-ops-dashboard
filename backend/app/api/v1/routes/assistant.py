from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.assistant import AssistantEvaluationRead
from app.services.assistant import (
    AssistantError,
    evaluate_notification,
    get_latest_evaluation,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/evaluation/{notification_id}", response_model=AssistantEvaluationRead)
async def get_evaluation(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> AssistantEvaluationRead:
    evaluation = await get_latest_evaluation(db, notification_id)
    if evaluation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No evaluation exists for this notification yet. "
                "POST to /evaluate to create one."
            ),
        )
    return AssistantEvaluationRead.model_validate(evaluation)


@router.post("/evaluate/{notification_id}", response_model=AssistantEvaluationRead)
async def evaluate(
    notification_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AssistantEvaluationRead:
    try:
        evaluation = await evaluate_notification(db, notification_id)
    except AssistantError as exc:
        if "Notification not found" in str(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="assistant.evaluate",
        entity_type="notification",
        entity_id=str(notification_id),
        user_id=current_user.id,
        ip_address=ip,
        detail={
            "evaluation_id": str(evaluation.id),
            "model": evaluation.model,
            "procedures_used": evaluation.procedures_used,
            "had_error": evaluation.error is not None,
        },
    )
    await db.commit()
    await db.refresh(evaluation)
    return AssistantEvaluationRead.model_validate(evaluation)
