from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, validator
from typing import Optional

class WeatherZoneBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    center_latitude: float = Field(..., ge=-90.0, le=90.0)
    center_longitude: float = Field(..., ge=-180.0, le=180.0)
    radius_km: float = Field(default=10.0, ge=1.0, le=50.0)
    is_active: bool = True

    @validator('name')
    def name_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError('name must not be empty')
        return v.strip()

class WeatherZoneCreate(WeatherZoneBase):
    pass

class WeatherZoneUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    center_latitude: Optional[float] = Field(None, ge=-90.0, le=90.0)
    center_longitude: Optional[float] = Field(None, ge=-180.0, le=180.0)
    radius_km: Optional[float] = Field(None, ge=1.0, le=50.0)
    is_active: Optional[bool] = None

class WeatherZone(WeatherZoneBase):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class FieldWeatherZoneBase(BaseModel):
    field_id: UUID
    zone_id: UUID

class FieldWeatherZoneCreate(FieldWeatherZoneBase):
    pass

class FieldWeatherZone(FieldWeatherZoneBase):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime

    class Config:
        from_attributes = True 