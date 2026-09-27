"""
Weather queries over the TimescaleDB hypertables.
- Current conditions: OpenWeather, cached as the latest observation within a TTL.
- Forecast: rows loaded by the SMN ETL, plus a per-day summary used by alerts and the agent.
"""
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.base import utcnow

from .models import WeatherForecast, WeatherObservation, round_coord
from .openweather import OpenWeatherAdapter

logger = logging.getLogger(__name__)

HUMID_THRESHOLD = 85.0
HUMID_TEMP_RANGE = (15.0, 28.0)


@dataclass
class DailyForecast:
    date: date
    tmin: Optional[float]
    tmax: Optional[float]
    precipitation_mm: Optional[float]
    max_humidity: Optional[float]
    humid_warm_hours: float
    max_wind_speed: Optional[float]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["date"] = self.date.isoformat()
        return data


def _observation_dict(obs: WeatherObservation) -> dict:
    return {
        "time": obs.time.isoformat(),
        "latitude": obs.latitude,
        "longitude": obs.longitude,
        "source": obs.source,
        "temperature": obs.temperature,
        "feels_like": obs.feels_like,
        "humidity": obs.humidity,
        "pressure": obs.pressure,
        "wind_speed": obs.wind_speed,
        "wind_direction": obs.wind_direction,
        "precipitation": obs.precipitation,
        "clouds": obs.clouds,
        "description": obs.description,
    }


class WeatherService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        openweather: OpenWeatherAdapter,
        current_cache_ttl: int = 900,
        timezone_name: str = "America/Argentina/Buenos_Aires",
        smn_hourly_step: int = 3,
    ):
        self.session_factory = session_factory
        self.openweather = openweather
        self.ttl = timedelta(seconds=current_cache_ttl)
        self.tz = ZoneInfo(timezone_name)
        self.hourly_step = smn_hourly_step

    # ---------------------------------------------------------------- current (OpenWeather)

    async def current(self, latitude: float, longitude: float) -> Optional[dict]:
        lat, lon = round_coord(latitude), round_coord(longitude)
        async with self.session_factory() as session:
            cached = (
                await session.execute(
                    select(WeatherObservation)
                    .where(
                        WeatherObservation.latitude == lat,
                        WeatherObservation.longitude == lon,
                        WeatherObservation.source == "openweather",
                        WeatherObservation.time >= utcnow() - self.ttl,
                    )
                    .order_by(WeatherObservation.time.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if cached:
            return _observation_dict(cached)

        data = await self.openweather.get_current_weather(lat, lon)
        if data is None:
            return None
        row = {
            "time": utcnow(),
            "latitude": lat,
            "longitude": lon,
            "source": "openweather",
            "temperature": data.temperature,
            "feels_like": data.feels_like,
            "humidity": data.humidity,
            "pressure": data.pressure,
            "wind_speed": data.wind_speed,
            "wind_direction": data.wind_direction,
            "precipitation": data.precipitation,
            "clouds": data.clouds,
            "description": data.description,
            "raw": data.to_dict(),
        }
        async with self.session_factory() as session:
            await session.execute(insert(WeatherObservation.__table__).values(row).on_conflict_do_nothing())
            await session.commit()
        row.pop("raw")
        row["time"] = row["time"].isoformat()
        return row

    async def history(self, latitude: float, longitude: float, hours_back: int = 24) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(WeatherObservation)
                    .where(
                        WeatherObservation.latitude == round_coord(latitude),
                        WeatherObservation.longitude == round_coord(longitude),
                        WeatherObservation.time >= utcnow() - timedelta(hours=hours_back),
                    )
                    .order_by(WeatherObservation.time)
                )
            ).scalars().all()
        return [_observation_dict(r) for r in rows]

    async def health(self) -> dict:
        return await self.openweather.health_check()

    # ---------------------------------------------------------------- forecast (SMN)

    async def forecast_rows(
        self, latitude: float, longitude: float, hours: int = 72, resolution: Optional[str] = None
    ) -> list[WeatherForecast]:
        start = utcnow() - timedelta(hours=1)
        stmt = select(WeatherForecast).where(
            WeatherForecast.latitude == round_coord(latitude),
            WeatherForecast.longitude == round_coord(longitude),
            WeatherForecast.time >= start,
            WeatherForecast.time <= start + timedelta(hours=hours + 24),
        )
        if resolution:
            stmt = stmt.where(WeatherForecast.resolution == resolution)
        async with self.session_factory() as session:
            return list((await session.execute(stmt.order_by(WeatherForecast.time))).scalars().all())

    async def daily_forecast(self, latitude: float, longitude: float, days: int = 3) -> list[DailyForecast]:
        rows = await self.forecast_rows(latitude, longitude, hours=days * 24)
        today = datetime.now(self.tz).date()
        hourly: dict[date, list[WeatherForecast]] = defaultdict(list)
        daily: dict[date, WeatherForecast] = {}
        for r in rows:
            local_day = r.time.astimezone(self.tz).date()
            if r.resolution == "24h":
                # SMN stamps daily files at 00 UTC of the day they describe.
                daily[r.time.astimezone(ZoneInfo("UTC")).date()] = r
            else:
                hourly[local_day].append(r)

        result = []
        for offset in range(days):
            day = today + timedelta(days=offset)
            hours_rows = sorted(hourly.get(day, []), key=lambda r: r.time)
            temps = [r.temperature for r in hours_rows if r.temperature is not None]
            hums = [r.humidity for r in hours_rows if r.humidity is not None]
            winds = [r.wind_speed for r in hours_rows if r.wind_speed is not None]
            accum = [r.precipitation_accum for r in hours_rows if r.precipitation_accum is not None]
            humid_warm = sum(
                self.hourly_step
                for r in hours_rows
                if r.humidity is not None
                and r.temperature is not None
                and r.humidity >= HUMID_THRESHOLD
                and HUMID_TEMP_RANGE[0] <= r.temperature <= HUMID_TEMP_RANGE[1]
            )
            d = daily.get(day)
            tmin = d.tmin if d and d.tmin is not None else (min(temps) if temps else None)
            tmax = d.tmax if d and d.tmax is not None else (max(temps) if temps else None)
            if tmin is None and tmax is None and not hums:
                continue
            result.append(
                DailyForecast(
                    date=day,
                    tmin=tmin,
                    tmax=tmax,
                    precipitation_mm=round(max(accum) - min(accum), 1) if len(accum) > 1 else None,
                    max_humidity=max(hums) if hums else None,
                    humid_warm_hours=float(humid_warm),
                    max_wind_speed=max(winds) if winds else None,
                )
            )
        return result

    async def forecast_issued_at(self, latitude: float, longitude: float) -> Optional[datetime]:
        rows = await self.forecast_rows(latitude, longitude, hours=1)
        return max((r.issued_at for r in rows), default=None)
