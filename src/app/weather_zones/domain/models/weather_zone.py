from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

class WeatherZoneBase(BaseModel):
    name: str
    center_latitude: float = Field(..., ge=-90, le=90)
    center_longitude: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(..., gt=0, le=50)
    is_active: bool = True

class WeatherZoneCreate(WeatherZoneBase):
    pass

class WeatherZoneUpdate(BaseModel):
    name: Optional[str] = None
    center_latitude: Optional[float] = Field(None, ge=-90, le=90)
    center_longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_km: Optional[float] = Field(None, gt=0, le=50)
    is_active: Optional[bool] = None

class WeatherZone(WeatherZoneBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class FieldWeatherZone(BaseModel):
    field_id: UUID
    zone_id: UUID
    distance_km: float
    created_at: datetime

    class Config:
        from_attributes = True 