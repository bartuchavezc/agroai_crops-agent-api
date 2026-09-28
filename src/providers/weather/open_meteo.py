"""
Open-Meteo adapter (https://open-meteo.com): no API key, no registration, generous free tier
(10k calls/day). Fills the gap the SMN forecast doesn't cover — wind and solar radiation — needed for
evapotranspiration, plus UV and humidity for general weather context. Forecast and historical archive
share the same hourly variable set and response shape, so both parse through the same helper.
"""
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class OpenMeteoHour:
    time: str  # ISO 8601, local time at the point (timezone=auto)
    temperature: Optional[float]  # °C
    humidity: Optional[float]  # % relative humidity
    wind_speed_10m: Optional[float]  # km/h
    shortwave_radiation: Optional[float]  # W/m2
    uv_index: Optional[float]  # forecast only; not available in the historical archive


class OpenMeteoAdapter:
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
    _BASE_HOURLY_VARS = "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation"
    _FORECAST_HOURLY_VARS = _BASE_HOURLY_VARS + ",uv_index"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    async def _get(self, url: str, params: dict) -> Optional[dict]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Open-Meteo error {response.status}: {await response.text()}")
                        return None
                    return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Open-Meteo HTTP error: {e}")
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"Unexpected error calling Open-Meteo: {e}")
            return None

    @staticmethod
    def _parse_hourly(data: dict) -> list[OpenMeteoHour]:
        hourly = data.get("hourly") or {}
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        hums = hourly.get("relative_humidity_2m") or []
        winds = hourly.get("wind_speed_10m") or []
        rad = hourly.get("shortwave_radiation") or []
        uv = hourly.get("uv_index") or []

        def at(series: list, i: int) -> Optional[float]:
            return series[i] if i < len(series) else None

        return [
            OpenMeteoHour(
                time=t,
                temperature=at(temps, i),
                humidity=at(hums, i),
                wind_speed_10m=at(winds, i),
                shortwave_radiation=at(rad, i),
                uv_index=at(uv, i),
            )
            for i, t in enumerate(times)
        ]

    async def forecast_hourly(self, latitude: float, longitude: float, days: int = 3) -> list[OpenMeteoHour]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": self._FORECAST_HOURLY_VARS,
            "forecast_days": max(1, min(days, 16)),
            "timezone": "auto",
            "wind_speed_unit": "ms",  # matches the SMN forecast's convention (m/s), not the km/h default
        }
        data = await self._get(self.FORECAST_URL, params)
        return self._parse_hourly(data) if data else []

    async def historical_hourly(
        self, latitude: float, longitude: float, start: date, end: date
    ) -> list[OpenMeteoHour]:
        """Historical archive, back to 1940. No uv_index in this endpoint."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": self._BASE_HOURLY_VARS,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "auto",
            "wind_speed_unit": "ms",
        }
        data = await self._get(self.ARCHIVE_URL, params)
        return self._parse_hourly(data) if data else []

    async def health_check(self) -> dict:
        rows = await self.forecast_hourly(-34.6037, -58.3816, days=1)
        if rows:
            return {"status": "healthy", "message": "Open-Meteo is accessible"}
        return {"status": "degraded", "message": "Open-Meteo returned no data"}
