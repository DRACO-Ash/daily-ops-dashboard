from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ElsetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    udl_id: Optional[str] = None
    sat_no: int
    epoch: datetime
    mean_motion: Optional[float] = None
    eccentricity: Optional[float] = None
    inclination: Optional[float] = None
    raan: Optional[float] = None
    arg_of_perigee: Optional[float] = None
    mean_anomaly: Optional[float] = None
    rev_no: Optional[int] = None
    bstar: Optional[float] = None
    mean_motion_dot: Optional[float] = None
    mean_motion_ddot: Optional[float] = None
    semi_major_axis: Optional[float] = None
    period: Optional[float] = None
    apogee: Optional[float] = None
    perigee: Optional[float] = None
    line1: Optional[str] = None
    line2: Optional[str] = None
    classification_marking: Optional[str] = None
    data_mode: Optional[str] = None
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ElsetDetail(ElsetRead):
    raw: dict[str, Any]


class ElsetPage(BaseModel):
    items: list[ElsetRead]
    total: int
    limit: int
    offset: int


class ElsetIngestRequest(BaseModel):
    epoch_gte: datetime
    sat_no: Optional[int] = None
    max_results: Optional[int] = None


class ElsetIngestResponse(BaseModel):
    pulled: int
    inserted: int
    updated: int
    skipped: int
