from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MattermostMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mm_post_id: str
    channel_id: str
    channel_name: Optional[str] = None
    user_id: str
    user_display_name: Optional[str] = None
    posted_at: datetime
    message: str
    post_type: Optional[str] = None
    root_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MattermostMessagePage(BaseModel):
    items: list[MattermostMessageRead]
    total: int
    limit: int
    offset: int
