from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, String, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

from src.app.weather_zones.domain.base import Base

class WeatherZone(Base):
    __tablename__ = "weather_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String, nullable=False)
    # Using Numeric(9,6) for coordinates:
    # - 9 total digits
    # - 6 decimal places
    # This gives us precision up to 0.000001 degrees (about 11cm at the equator)
    center_latitude = Column(Numeric(9, 6), nullable=False)
    center_longitude = Column(Numeric(9, 6), nullable=False)
    radius_km = Column(Numeric(10, 2), nullable=False)  # Up to 99999999.99 km
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)

    def __repr__(self):
        return f"<WeatherZone(id={self.id}, name='{self.name}', is_active={self.is_active})>" 