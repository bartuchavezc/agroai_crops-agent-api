"""
Weather queries over the TimescaleDB hypertables.
- Current conditions: OpenWeather, cached as the latest observation within a TTL.
- Forecast: rows loaded by the SMN ETL, plus a per-day summary used by alerts and the agent.
"""
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.base import utcnow

from .models import WeatherForecast, WeatherObservation, round_coord
from .open_meteo import OpenMeteoAdapter
from .summary import summarize_daily
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


RECENT_SUMMARY_TTL_HOURS = 6


class WeatherService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        openweather: OpenWeatherAdapter,
        open_meteo: OpenMeteoAdapter,
        current_cache_ttl: int = 900,
        timezone_name: str = "America/Argentina/Buenos_Aires",
        smn_hourly_step: int = 3,
    ):
        self.session_factory = session_factory
        self.openweather = openweather
        self.open_meteo = open_meteo
        self._recent_cache: dict[tuple, tuple[datetime, dict]] = {}
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
        self, latitude: float, longitude: float, hours: int = 72, resolution: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[WeatherForecast]:
        start = since or utcnow() - timedelta(hours=1)
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
        today = datetime.now(self.tz).date()
        # Read from the start of today, not "now - 1h": SMN daily rows are stamped at 00 UTC of the day they
        # describe, which in Argentina (UTC-3) is 21:00 of the previous local day. With a "now - 1h" window,
        # from 22:00 local on, tomorrow's daily row (tmin/tmax) was already "in the past" and got dropped —
        # and today's hourly rows before now were missing from today's min/max too.
        local_midnight = datetime.combine(today, time.min, tzinfo=self.tz)
        since = min(local_midnight, datetime.combine(today, time.min, tzinfo=timezone.utc))
        hours = int((utcnow() - since).total_seconds() // 3600) + days * 24
        rows = await self.forecast_rows(latitude, longitude, hours=hours, since=since)
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

    # ---------------------------------------------------------------- Open-Meteo (UV, humidity, wind, radiation)

    async def open_meteo_current(self, latitude: float, longitude: float) -> Optional[dict]:
        """Current-ish UV/humidity/wind/radiation context, cached like current() but under source='open_meteo'
        so it coexists with the OpenWeather row for the same point. UV in particular has no other source."""
        lat, lon = round_coord(latitude), round_coord(longitude)
        async with self.session_factory() as session:
            cached = (
                await session.execute(
                    select(WeatherObservation)
                    .where(
                        WeatherObservation.latitude == lat,
                        WeatherObservation.longitude == lon,
                        WeatherObservation.source == "open_meteo",
                        WeatherObservation.time >= utcnow() - self.ttl,
                    )
                    .order_by(WeatherObservation.time.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if cached:
            raw = cached.raw or {}
            return {"uv_index": raw.get("uv_index"), "humidity": cached.humidity, "wind_speed": cached.wind_speed}

        hours = await self.open_meteo.forecast_hourly(lat, lon, days=1)
        if not hours:
            return None
        now_naive = datetime.now(self.tz).replace(tzinfo=None, minute=0, second=0, microsecond=0)
        closest = min(hours, key=lambda h: abs(datetime.fromisoformat(h.time) - now_naive))
        row = {
            "time": utcnow(),
            "latitude": lat,
            "longitude": lon,
            "source": "open_meteo",
            "humidity": closest.humidity,
            "wind_speed": closest.wind_speed_10m,
            "raw": {"uv_index": closest.uv_index, "shortwave_radiation": closest.shortwave_radiation},
        }
        async with self.session_factory() as session:
            await session.execute(insert(WeatherObservation.__table__).values(row).on_conflict_do_nothing())
            await session.commit()
        return {"uv_index": closest.uv_index, "humidity": closest.humidity, "wind_speed": closest.wind_speed_10m}

    async def recent_summary(self, latitude: float, longitude: float, days: int = 30) -> dict:
        """How the last `days` days went at the point (Open-Meteo): see `summarize_daily`. Empty when the provider
        has nothing. Kept in memory for a few hours per point: the past does not change and an agent turn may ask
        for it more than once."""
        days = max(7, min(days, 60))
        key = (round_coord(latitude), round_coord(longitude), days)
        cached = self._recent_cache.get(key)
        if cached and cached[0] > utcnow():
            return cached[1]
        summary = summarize_daily(await self.open_meteo.recent_daily(key[0], key[1], days))
        if summary:
            self._recent_cache[key] = (utcnow() + timedelta(hours=RECENT_SUMMARY_TTL_HOURS), summary)
        return summary

    async def daily_agro(self, latitude: float, longitude: float, days: int = 1) -> list[dict]:
        """Per-day wind/radiation/humidity averages from Open-Meteo, cached in weather_forecasts under
        source='open_meteo'/resolution='24h'. SMN doesn't carry wind or radiation, and evapotranspiration
        (FAO-56 Penman-Monteith) needs both."""
        lat, lon = round_coord(latitude), round_coord(longitude)
        days = max(1, min(days, 14))
        start = utcnow() - timedelta(hours=6)
        async with self.session_factory() as session:
            cached = (
                await session.execute(
                    select(WeatherForecast)
                    .where(
                        WeatherForecast.latitude == lat,
                        WeatherForecast.longitude == lon,
                        WeatherForecast.source == "open_meteo",
                        WeatherForecast.resolution == "24h",
                        WeatherForecast.time >= start,
                    )
                    .order_by(WeatherForecast.time)
                )
            ).scalars().all()
        if len(cached) >= days:
            return [self._agro_day_dict(r) for r in cached[:days]]

        hours = await self.open_meteo.forecast_hourly(lat, lon, days=days + 1)
        if not hours:
            return [self._agro_day_dict(r) for r in cached]

        by_day: dict[date, list] = defaultdict(list)
        for h in hours:
            by_day[datetime.fromisoformat(h.time).date()].append(h)
        issued = utcnow()
        rows = []
        for day in sorted(by_day)[:days]:
            day_hours = by_day[day]
            winds = [h.wind_speed_10m for h in day_hours if h.wind_speed_10m is not None]
            rads = [h.shortwave_radiation for h in day_hours if h.shortwave_radiation is not None]
            hums = [h.humidity for h in day_hours if h.humidity is not None]
            rows.append(
                {
                    "time": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                    "latitude": lat,
                    "longitude": lon,
                    "source": "open_meteo",
                    "resolution": "24h",
                    "issued_at": issued,
                    "wind_speed": (sum(winds) / len(winds)) if winds else None,
                    "radiation": (sum(rads) / len(rads)) if rads else None,
                    "humidity": (sum(hums) / len(hums)) if hums else None,
                }
            )
        async with self.session_factory() as session:
            for row in rows:
                stmt = insert(WeatherForecast.__table__).values(row)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["time", "latitude", "longitude", "source", "resolution"],
                    set_={
                        "wind_speed": stmt.excluded.wind_speed,
                        "radiation": stmt.excluded.radiation,
                        "humidity": stmt.excluded.humidity,
                        "issued_at": stmt.excluded.issued_at,
                    },
                )
                await session.execute(stmt)
            await session.commit()
        return [
            {"date": day.isoformat(), **self._agro_row_dict(row)}
            for day, row in zip(sorted(by_day)[:days], rows, strict=True)
        ]

    @staticmethod
    def _agro_day_dict(r: WeatherForecast) -> dict:
        return {
            "date": r.time.astimezone(timezone.utc).date().isoformat(),
            "wind_speed": r.wind_speed,
            "radiation": r.radiation,
            "humidity": r.humidity,
        }

    @staticmethod
    def _agro_row_dict(row: dict) -> dict:
        return {"wind_speed": row["wind_speed"], "radiation": row["radiation"], "humidity": row["humidity"]}
