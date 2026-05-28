from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    timestamp: datetime
    user_id: Optional[UUID] = None
    action_type: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    ip_address: Optional[str] = None
    detail: Optional[str] = None
    previous_hash: Optional[str] = None
    entry_hash: str


class AuditLogPage(BaseModel):
    items: list[AuditLogRead]
    total: int
    limit: int
    offset: int
