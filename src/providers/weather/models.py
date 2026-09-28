"""
Weather time series stored as TimescaleDB hypertables (created in the Alembic migration).
Coordinates are rounded to 3 decimals (~100 m) so the same place always maps to the same key.
"""
from sqlalchemy import Column, DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from src.shared.database import Base

COORD_DECIMALS = 3


def round_coord(value: float) -> float:
    return round(float(value), COORD_DECIMALS)


class WeatherObservation(Base):
    """Current conditions (OpenWeather). Also acts as the short-lived cache of /weather/current."""
    __tablename__ = "weather_observations"
    __table_args__ = (Index("ix_weather_observations_point_time", "latitude", "longitude", "time"),)

    time = Column(DateTime(timezone=True), primary_key=True)
    latitude = Column(Float, primary_key=True)
    longitude = Column(Float, primary_key=True)
    source = Column(String(20), primary_key=True, default="openweather")
    temperature = Column(Float)
    feels_like = Column(Float)
    humidity = Column(Float)
    pressure = Column(Float)
    wind_speed = Column(Float)
    wind_direction = Column(Float)
    precipitation = Column(Float)
    clouds = Column(Float)
    description = Column(Text)
    raw = Column(JSONB)


class WeatherForecast(Base):
    """Forecast values per point. resolution '1h' = hourly model output, '24h' = daily Tmin/Tmax."""
    __tablename__ = "weather_forecasts"
    __table_args__ = (Index("ix_weather_forecasts_point_time", "latitude", "longitude", "time"),)

    time = Column(DateTime(timezone=True), primary_key=True)
    latitude = Column(Float, primary_key=True)
    longitude = Column(Float, primary_key=True)
    source = Column(String(20), primary_key=True, default="smn_wrf")
    resolution = Column(String(4), primary_key=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    temperature = Column(Float)
    humidity = Column(Float)
    precipitation_accum = Column(Float)
    wind_speed = Column(Float)
    tmin = Column(Float)
    tmax = Column(Float)
    radiation = Column(Float)  # shortwave radiation, W/m2 daily average (Open-Meteo; SMN rows leave this null)
