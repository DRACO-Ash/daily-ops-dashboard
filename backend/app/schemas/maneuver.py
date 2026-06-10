from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ManeuverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    udl_id: Optional[str] = None
    data_mode: Optional[str] = None
    source: Optional[str] = None
    classification_marking: Optional[str] = None
    created_by: Optional[str] = None
    orig_network: Optional[str] = None
    origin: Optional[str] = None
    udl_created_at: Optional[datetime] = None

    sat_no: Optional[int] = None
    event_start_time: Optional[datetime] = None
    event_stop_time: Optional[datetime] = None
    mnvr_type: Optional[str] = None
    description: Optional[str] = None
    delta_v: Optional[float] = None
    thrust_magnitude: Optional[float] = None
    thrust_duration: Optional[float] = None
    propulsion_type: Optional[str] = None
    maneuver_status: Optional[str] = None
    responsible_nation: Optional[str] = None

    created_at: datetime
    updated_at: datetime


class ManeuverDetail(ManeuverRead):
    raw: dict[str, Any]


class ManeuverPage(BaseModel):
    items: list[ManeuverRead]
    total: int
    limit: int
    offset: int
