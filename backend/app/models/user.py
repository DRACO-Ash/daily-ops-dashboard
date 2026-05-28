import enum
import uuid

from sqlalchemy import Boolean, Column, String
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    ANALYST = "analyst"
    OPERATOR = "operator"
    ADMIN = "admin"


class User(Base, TimestampMixin):
    __tablename__ = "app_user"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.ANALYST.value)
    is_active = Column(Boolean, nullable=False, default=True)
