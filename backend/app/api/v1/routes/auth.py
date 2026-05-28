from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.session import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RefreshResponse,
    TokenResponse,
    UserRead,
)
from app.services.audit import write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

_invalid_credentials = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid username or password",
)

_invalid_refresh = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid refresh token",
)


async def _audit_login(
    db: AsyncSession,
    *,
    user: Optional[User],
    username: str,
    ip: Optional[str],
    success: bool,
    reason: Optional[str] = None,
) -> None:
    detail: dict[str, Any] = {"success": success, "username": username}
    if reason is not None:
        detail["reason"] = reason
    await write_audit(
        db,
        action_type="auth.user.login",
        entity_type="user",
        entity_id=str(user.id) if user is not None else None,
        user_id=user.id if user is not None else None,
        ip_address=ip,
        detail=detail,
    )
    await db.commit()


async def _audit_refresh(
    db: AsyncSession,
    *,
    user: Optional[User],
    ip: Optional[str],
    success: bool,
    reason: Optional[str] = None,
) -> None:
    detail: dict[str, Any] = {"success": success}
    if reason is not None:
        detail["reason"] = reason
    await write_audit(
        db,
        action_type="auth.token.refresh",
        entity_type="user",
        entity_id=str(user.id) if user is not None else None,
        user_id=user.id if user is not None else None,
        ip_address=ip,
        detail=detail,
    )
    await db.commit()


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    username = payload.username.strip().lower()
    ip = request.client.host if request.client else None

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if user is None:
        await _audit_login(
            db, user=None, username=username, ip=ip, success=False, reason="unknown_user"
        )
        raise _invalid_credentials

    if not user.is_active:
        await _audit_login(
            db, user=user, username=username, ip=ip, success=False, reason="inactive_user"
        )
        raise _invalid_credentials

    if not verify_password(payload.password, user.password_hash):
        await _audit_login(
            db, user=user, username=username, ip=ip, success=False, reason="wrong_password"
        )
        raise _invalid_credentials

    await _audit_login(db, user=user, username=username, ip=ip, success=True)

    subject = str(user.id)
    return TokenResponse(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RefreshResponse:
    ip = request.client.host if request.client else None
    decoded = decode_token(payload.refresh_token)

    if decoded is None or decoded.get("type") != "refresh":
        await _audit_refresh(db, user=None, ip=ip, success=False, reason="invalid_token")
        raise _invalid_refresh

    subject = decoded.get("sub")
    if not subject:
        await _audit_refresh(db, user=None, ip=ip, success=False, reason="missing_subject")
        raise _invalid_refresh

    try:
        user_id = UUID(subject)
    except (ValueError, TypeError) as exc:
        await _audit_refresh(db, user=None, ip=ip, success=False, reason="malformed_subject")
        raise _invalid_refresh from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        await _audit_refresh(db, user=user, ip=ip, success=False, reason="inactive_user")
        raise _invalid_refresh

    await _audit_refresh(db, user=user, ip=ip, success=True)
    return RefreshResponse(access_token=create_access_token(subject))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    ip = request.client.host if request.client else None
    await write_audit(
        db,
        action_type="auth.user.logout",
        entity_type="user",
        entity_id=str(current_user.id),
        user_id=current_user.id,
        ip_address=ip,
        detail={},
    )
    await db.commit()


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
