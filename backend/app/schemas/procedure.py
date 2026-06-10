from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ProcedureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str] = None
    filename: str
    content_type: str
    size_bytes: int
    file_hash: str
    uploaded_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class ProcedureContent(ProcedureRead):
    """Procedure metadata plus inlined file content for previewable types."""

    content: Optional[str] = None
    content_truncated: bool = False


class ProcedurePage(BaseModel):
    items: list[ProcedureRead]
    total: int
