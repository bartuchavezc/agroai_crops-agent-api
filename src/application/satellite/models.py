"""
Satellite data per field (Copernicus). Low volume — ~70 Sentinel-2 + ~30-60 Sentinel-1 observations per
field per year — so plain (non-hypertable) tables with a composite index are enough:

- `field_satellite_observations`: the time series. One row per (field, acquisition date, source), upserted,
  so re-ingesting the same window (late tiles, an on-demand refresh racing the daily batch) never
  duplicates. Only aggregated numbers, never a raw tile.
- `field_satellite_sync`: per (field, source), how far back the series reaches, when it was last synced
  and over which geometry — a redrawn boundary means different pixels, so the series is rebuilt.
- `copernicus_usage`: processing units spent per month and kind (batch / on-demand), from the API's own
  header, to keep the free tier's monthly budget.
- `zone_satellite_readings`: only the saved NDVI map images now (rows with image_identifier). Older rows
  holding stats are legacy 30-day mosaics dated at request time, superseded by the series.
"""
import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

SOURCE_S2 = "sentinel2"
SOURCE_S1 = "sentinel1"


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
    pixel_count = Column(Integer)  # only set when the reading was scoped to the field's drawn boundary
    source = Column(String(20), nullable=False, default="sentinel2")
    image_identifier = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class FieldSatelliteObservation(Base):
    __tablename__ = "field_satellite_observations"
    __table_args__ = (
        UniqueConstraint("field_id", "observed_on", "source", name="uq_field_satellite_observations_field_date_source"),
        Index("ix_field_satellite_observations_field_source_date", "field_id", "source", "observed_on"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    observed_on = Column(Date, nullable=False)  # the satellite pass date, not when we asked for it
    source = Column(String(20), nullable=False)  # sentinel2 | sentinel1

    # How much of the field the numbers below actually describe (clouds/shadows/snow masked out).
    total_pixels = Column(Integer)
    valid_pixels = Column(Integer)
    valid_fraction = Column(Float)

    # Sentinel-2
    ndvi_mean = Column(Float)
    ndvi_std = Column(Float)
    ndvi_min = Column(Float)
    ndvi_max = Column(Float)
    ndvi_p10 = Column(Float)
    ndvi_p50 = Column(Float)
    ndvi_p90 = Column(Float)
    ndre_mean = Column(Float)  # red-edge: keeps separating dense canopies where NDVI saturates
    ndre_std = Column(Float)
    ndmi_mean = Column(Float)  # SWIR moisture: water content of the canopy (water stress)
    ndmi_std = Column(Float)
    evi_mean = Column(Float)  # soil/atmosphere-corrected greenness, less saturable than NDVI
    evi_std = Column(Float)
    ndwi_mean = Column(Float)  # open water / waterlogging

    # Sentinel-1 (gamma0, terrain-flattened)
    vv_db_mean = Column(Float)
    vh_db_mean = Column(Float)
    vh_vv_db = Column(Float)
    rvi_mean = Column(Float)
    orbit_direction = Column(String(12))

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class FieldSatelliteSync(Base):
    __tablename__ = "field_satellite_sync"

    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), primary_key=True)
    source = Column(String(20), primary_key=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    geometry_hash = Column(String(16), nullable=False)
    history_from = Column(Date, nullable=False)  # the series covers [history_from, synced_to]
    synced_to = Column(Date, nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class CopernicusUsage(Base):
    __tablename__ = "copernicus_usage"

    month = Column(Date, primary_key=True)  # first day of the month (UTC)
    kind = Column(String(12), primary_key=True)  # batch | on_demand
    processing_units = Column(Float, nullable=False, default=0.0)
    requests = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
