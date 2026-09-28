"""
Zone-level satellite readings (Sentinel-2 via Copernicus): only the aggregated numbers, never a raw
tile — low volume, so a plain (non-hypertable) table with an index on (field_id, captured_at) is enough.
"""
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow


class ZoneSatelliteReading(Base):
    __tablename__ = "zone_satellite_readings"
    __table_args__ = (Index("ix_zone_satellite_readings_field_time", "field_id", "captured_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    ndvi_mean = Column(Float)
    ndvi_min = Column(Float)
    ndvi_max = Column(Float)
    ndwi_mean = Column(Float)
    source = Column(String(20), nullable=False, default="sentinel2")
    image_identifier = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
