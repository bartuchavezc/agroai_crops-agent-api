from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ZoneSatelliteReadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    field_id: UUID
    captured_at: datetime
    ndvi_mean: Optional[float] = None
    ndvi_min: Optional[float] = None
    ndvi_max: Optional[float] = None
    ndwi_mean: Optional[float] = None
    pixel_count: Optional[int] = None
    source: str
    image_identifier: Optional[str] = None


class ZoneSatelliteStatus(BaseModel):
    field_id: UUID
    field_name: str
    reading: Optional[ZoneSatelliteReadingRead] = None
    baseline_ndvi_mean: Optional[float] = None
    assessment: str
    alerts: list[str] = []
    boundary_scoped: bool = False
    pixel_count_caveat: Optional[str] = None
    # The last clear pass against the one before it (raw NDVI means of the two passes).
    previous_ndvi_mean: Optional[float] = None
    previous_date: Optional[date] = None
    ndvi_delta: Optional[float] = None
    # A pass counts as clear (used) only with at least this fraction of the field's pixels cloud-free.
    min_valid_fraction: Optional[float] = None
    # The field's series read against its own history (see application/satellite/analytics.py
    # SeriesAnalysis): last clear pass, every index vs its normal/last year, season stage, radar
    # continuity signal and data-quality caveats.
    analysis: Optional[dict[str, Any]] = None
