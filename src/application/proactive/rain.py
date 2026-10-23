"""Rain at each field, written into the bitácora by the system: "no regué porque llovió" then has the rain to cite,
and a week's summary knows how much fell. Open-Meteo's daily precipitation for the field's point (a model estimate,
not a gauge): only past days, only above a threshold, once per field and day."""
import logging
from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.application.farm.models import GROWING_LOT_STATUSES, FieldEvent
from src.shared.domain.base import utcnow

logger = logging.getLogger(__name__)

MIN_RAIN_MM = 1.0


class RainLogService:
    def __init__(self, farm_repository, weather_service, timezone_name: str, min_mm: float = MIN_RAIN_MM):
        self.repo = farm_repository
        self.weather = weather_service
        self.tz = ZoneInfo(timezone_name)
        self.min_mm = min_mm

    async def _logged(self, field_id, day: date) -> bool:
        async with self.repo.session_factory() as session:
            found = (await session.execute(
                select(FieldEvent.id).where(
                    FieldEvent.field_id == field_id, FieldEvent.type == "rain",
                    FieldEvent.data["date"].astext == day.isoformat(),
                ).limit(1)
            )).first()
        return found is not None

    async def log_field(self, field, days: int = 3, today: Optional[date] = None) -> int:
        """Rain of the last `days` complete days at one field; returns how many days were written."""
        today = today or datetime.now(self.tz).date()
        rows = await self.weather.open_meteo.recent_daily(field.latitude, field.longitude, days)
        written = 0
        for row in rows:
            day = date.fromisoformat(row["date"])
            mm = row.get("precipitation_mm")
            if day >= today or day < today - timedelta(days=days) or mm is None or mm < self.min_mm:
                continue
            if await self._logged(field.id, day):
                continue
            lots = await self.repo.list_lots(field.account_id, field_id=field.id, statuses=GROWING_LOT_STATUSES)
            await self.repo.create_event(
                FieldEvent(
                    account_id=field.account_id, field_id=field.id, type="rain", source="system",
                    occurred_at=datetime.combine(day, time(12), tzinfo=self.tz), quantity=round(mm, 1), unit="mm",
                    notes=f"Lluvia estimada: {mm:.1f} mm", data={"date": day.isoformat(), "source": "open_meteo"},
                ),
                lot_ids=[lot.id for lot in lots],
            )
            written += 1
        return written

    async def run(self, days: int = 3) -> dict:
        fields = await self.repo.list_all_fields_with_coordinates()
        written = failed = 0
        for field in fields:
            try:
                written += await self.log_field(field, days)
            except Exception:  # noqa: BLE001 - one field's weather must not stop the rest
                failed += 1
                logger.exception(f"Rain log failed for field {field.id}")
        logger.info(f"Rain log at {utcnow():%Y-%m-%d %H:%M}: {written} day(s) written, {failed} field(s) failed")
        return {"fields": len(fields), "written": written, "failed": failed}
