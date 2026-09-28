"""
NASA POWER adapter (https://power.larc.nasa.gov): no API key. Used for zone-level (~55km grid, same
"grid not per-plant" criterion already used for the SMN forecast) historical/average solar radiation
context — the radiation half of the free UV/humidity/historical combination from future.md. The
climatology endpoint gives 12 monthly averages in a single call, exactly the "your zone gets X on
average this time of year" framing the get_solar_radiation_context tool needs.
"""
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_MONTH_KEYS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
_FILL_VALUE_THRESHOLD = -900  # NASA POWER marks missing data as -999


@dataclass
class SolarClimatology:
    monthly_avg_radiation_mj_m2_day: dict[int, float]  # 1-12 -> MJ/m2/day (ALLSKY_SFC_SW_DWN)
    annual_avg_radiation_mj_m2_day: Optional[float]


class NasaPowerAdapter:
    BASE_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    async def solar_climatology(self, latitude: float, longitude: float) -> Optional[SolarClimatology]:
        params = {
            "parameters": "ALLSKY_SFC_SW_DWN",
            "community": "AG",
            "longitude": longitude,
            "latitude": latitude,
            "format": "JSON",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"NASA POWER error {response.status}: {await response.text()}")
                        return None
                    data = await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"NASA POWER HTTP error: {e}")
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"Unexpected error calling NASA POWER: {e}")
            return None

        try:
            series = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        except (KeyError, TypeError):
            return None

        monthly = {}
        for i, key in enumerate(_MONTH_KEYS, start=1):
            value = series.get(key)
            if value is not None and value > _FILL_VALUE_THRESHOLD:
                monthly[i] = value
        annual = series.get("ANN")
        return SolarClimatology(
            monthly_avg_radiation_mj_m2_day=monthly,
            annual_avg_radiation_mj_m2_day=(
                annual if annual is not None and annual > _FILL_VALUE_THRESHOLD else None
            ),
        )

    async def health_check(self) -> dict:
        result = await self.solar_climatology(-34.6037, -58.3816)
        if result and result.monthly_avg_radiation_mj_m2_day:
            return {"status": "healthy", "message": "NASA POWER is accessible"}
        return {"status": "degraded", "message": "NASA POWER returned no data"}
