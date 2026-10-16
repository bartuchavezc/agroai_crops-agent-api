"""
Proactive alerts: evaluate the forecast rules for every field that has coordinates and store
deduplicated alerts. Deterministic, no LLM involved, so it works for accounts without API keys.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.application.farm.repository import FarmRepository
from src.providers.weather.service import WeatherService

from .rules_engine import RulesEngine
from .service import AlertService

logger = logging.getLogger(__name__)


@dataclass
class ForecastAlertsResult:
    fields_evaluated: int = 0
    days_evaluated: int = 0
    alerts_created: int = 0


class ForecastAlertService:
    def __init__(
        self,
        farm_repository: FarmRepository,
        weather_service: WeatherService,
        alert_service: AlertService,
        rules_engine: RulesEngine,
        timezone_name: str,
        days: int = 3,
        field_rules=None,
    ):
        self.farm = farm_repository
        self.weather = weather_service
        self.alerts = alert_service
        self.rules = rules_engine
        self.tz = ZoneInfo(timezone_name)
        self.field_rules = field_rules  # FieldAlertRulesService: what each field switched off or tuned
        self.days = days

    async def run(self) -> ForecastAlertsResult:
        result = ForecastAlertsResult()
        for field in await self.farm.list_all_fields_with_coordinates():
            result.fields_evaluated += 1
            overrides = await self.field_rules.overrides(field.id) if self.field_rules else {}
            for day in await self.weather.daily_forecast(field.latitude, field.longitude, self.days):
                result.days_evaluated += 1
                context = {**day.to_dict(), "date": day.date.strftime("%d/%m")}
                for match in self.rules.evaluate(context, categories=["forecast"], overrides=overrides):
                    start = datetime.combine(day.date, time.min, tzinfo=self.tz)
                    created = await self.alerts.create_system_alert(
                        account_id=field.account_id,
                        field_id=field.id,
                        title=f"{field.name}: {match.message.split(':')[0]}",
                        message=match.message,
                        severity=match.severity.value,
                        alert_type="weather",
                        source="smn",
                        rule_id=match.rule_id,
                        recommendations=match.recommendations,
                        metadata={"forecast": day.to_dict()},
                        valid_from=start,
                        valid_to=start + timedelta(days=1),
                        dedupe_key=f"{field.id}:{match.rule_id}:{day.date.isoformat()}",
                    )
                    result.alerts_created += int(created)
        logger.info(f"Forecast alerts: {result}")
        return result
