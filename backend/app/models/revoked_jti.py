from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class RevokedJti(Base):
    __tablename__ = "revoked_jti"

    jti = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    revoked_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
