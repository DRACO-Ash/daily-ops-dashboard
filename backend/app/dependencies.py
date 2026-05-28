from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _credentials_error
    return authorization.split(" ", 1)[1].strip()


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_bearer_token(authorization)
    payload = decode_token(token)
    if payload is None:
        raise _credentials_error
    if payload.get("type") != "access":
        raise _credentials_error
    subject = payload.get("sub")
    if not subject:
        raise _credentials_error
    try:
        user_id = UUID(subject)
    except (ValueError, TypeError) as exc:
        raise _credentials_error from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise _credentials_error
    return user


def require_role(*allowed_roles: UserRole):
    allowed = {role.value for role in allowed_roles}

    async def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient privileges for this action",
            )
        return current_user

    return checker
