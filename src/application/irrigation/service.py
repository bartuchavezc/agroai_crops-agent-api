"""
Evapotranspiration-based irrigation guidance: FAO-56 Penman-Monteith ET0 (src/application/irrigation/
penman_monteith.py) from SMN (tmin/tmax) + Open-Meteo (wind, radiation, humidity), Kc from the crop
catalog with a family-default fallback (src/application/farm/kc_defaults.py), net against recent
irrigation events already logged. Deterministic math end to end, no LLM.
"""
import logging
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from src.application.alerts.rules_engine import RulesEngine
from src.application.alerts.service import AlertService
from src.application.farm.kc_defaults import kc_for_stage
from src.application.farm.models import ACTIVE_CROP_CYCLE_STATUSES
from src.application.farm.repository import FarmRepository
from src.application.farm.service import FarmService
from src.providers.weather.service import WeatherService
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .penman_monteith import build_et0_inputs, reference_et0_mm
from .schemas import CycleIrrigation, FieldIrrigationResult, IrrigationStatus

logger = logging.getLogger(__name__)

RECENT_IRRIGATION_WINDOW_DAYS = 3


def _irrigation_mm(events, area_m2: Optional[float], crop_cycle_id: Optional[UUID] = None) -> float:
    """Sum of irrigation events in liters/mm converted to mm depth over the field's area. Events tied to
    a specific crop_cycle_id only count for that cycle (plus field-wide events with no cycle, which wet
    everything); the field total counts every irrigation event regardless of tagging."""
    total_liters = 0.0
    total_mm = 0.0
    for e in events:
        if crop_cycle_id is not None and e.crop_cycle_id not in (None, crop_cycle_id):
            continue
        if e.quantity is None:
            continue
        unit = (e.unit or "").strip().lower()
        if unit in ("mm", "milimetros", "milímetros"):
            total_mm += e.quantity
        else:  # default: liters (the unit used by log_event's own docstring example)
            total_liters += e.quantity
    if area_m2 and area_m2 > 0:
        total_mm += total_liters / area_m2
    return round(total_mm, 1)


def _cycle_progress_pct(cycle, crop_master, today: date) -> float:
    if not cycle.planting_date or not crop_master or not crop_master.growth_period_days:
        return 50.0  # unknown stage: assume mid-season, the most common Kc
    days_elapsed = (today - cycle.planting_date).days
    return max(0.0, min(100.0, 100 * days_elapsed / crop_master.growth_period_days))


class EvapotranspirationService:
    def __init__(
        self,
        farm_service: FarmService,
        farm_repository: FarmRepository,
        weather_service: WeatherService,
        alert_service: AlertService,
        rules_engine: RulesEngine,
    ):
        self.farm = farm_service
        self.farm_repo = farm_repository
        self.weather = weather_service
        self.alerts = alert_service
        self.rules = rules_engine

    async def _et0_and_rain(self, latitude: float, longitude: float) -> tuple[Optional[float], float]:
        daily = await self.weather.daily_forecast(latitude, longitude, 1)
        agro = await self.weather.daily_agro(latitude, longitude, 1)
        today_forecast = daily[0] if daily else None
        today_agro = agro[0] if agro else {}
        inputs = build_et0_inputs(
            latitude=latitude,
            day_of_year=date.today().timetuple().tm_yday,
            tmax_c=today_forecast.tmax if today_forecast else None,
            tmin_c=today_forecast.tmin if today_forecast else None,
            humidity_pct=today_agro.get("humidity") or (today_forecast.max_humidity if today_forecast else None),
            wind_speed_10m_ms=today_agro.get("wind_speed"),
            radiation_w_m2=today_agro.get("radiation"),
        )
        et0 = round(reference_et0_mm(inputs), 1) if inputs else None
        rain_mm = today_forecast.precipitation_mm if today_forecast and today_forecast.precipitation_mm else 0.0
        return et0, rain_mm

    def _status_for(self, net_mm: float, rain_forecast_mm: float) -> tuple[IrrigationStatus, str]:
        rain_rules = self.rules.evaluate({"precipitation_mm": rain_forecast_mm, "date": "hoy"}, categories=["forecast"])
        heavy_rain = next((r for r in rain_rules if r.rule_id == "forecast_heavy_rain"), None)
        if heavy_rain:
            return "no_regar_lluvia", heavy_rain.message
        matches = self.rules.evaluate({"net_mm": net_mm}, categories=["irrigation"])
        if matches:
            return ("regar" if matches[0].rule_id == "irrigation_deficit" else "cubierto"), matches[0].message
        return "cubierto", "Riego cubierto."

    async def compute(self, actor: Actor, field_id: UUID) -> FieldIrrigationResult:
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates; irrigation guidance needs one.")

        et0, rain_forecast_mm = await self._et0_and_rain(field.latitude, field.longitude)
        since = utcnow() - timedelta(days=RECENT_IRRIGATION_WINDOW_DAYS)
        irrigation_events = await self.farm.list_events(
            actor, field_id=field_id, event_type="irrigation", since=since, limit=200
        )

        cycles_raw = await self.farm.list_crop_cycles(actor, field_id=field_id)
        active_cycles = [c for c in cycles_raw if c.status in ACTIVE_CROP_CYCLE_STATUSES]

        cycles: list[CycleIrrigation] = []
        kc_values: list[float] = []
        today = date.today()
        for cycle in active_cycles:
            crop_master = await self.farm.get_crop_master(actor, cycle.crop_master_id)
            progress = _cycle_progress_pct(cycle, crop_master, today)
            kc = kc_for_stage(
                crop_master.kc_initial, crop_master.kc_mid, crop_master.kc_late, crop_master.family, progress
            )
            kc_values.append(kc)
            if et0 is None:
                continue
            etc_mm = round(et0 * kc, 1)
            recent = _irrigation_mm(irrigation_events, field.area_m2, crop_cycle_id=cycle.id)
            net = round(etc_mm - recent, 1)
            status, message = self._status_for(net, rain_forecast_mm)
            cycles.append(
                CycleIrrigation(
                    crop_cycle_id=cycle.id,
                    crop_name=crop_master.name,
                    kc=kc,
                    etc_mm=etc_mm,
                    recent_irrigation_mm=recent,
                    net_mm=net,
                    status=status,
                    message=message,
                )
            )

        result = FieldIrrigationResult(
            field_id=field.id, field_name=field.name, et0_mm=et0 or 0.0, rain_forecast_mm=rain_forecast_mm,
            cycles=cycles,
        )
        if et0 is not None:
            field_kc = round(sum(kc_values) / len(kc_values), 2) if kc_values else 1.0
            field_etc = round(et0 * field_kc, 1)
            field_recent = _irrigation_mm(irrigation_events, field.area_m2)
            field_net = round(field_etc - field_recent, 1)
            status, message = self._status_for(field_net, rain_forecast_mm)
            result.field_kc = field_kc
            result.field_etc_mm = field_etc
            result.field_recent_irrigation_mm = field_recent
            result.field_net_mm = field_net
            result.field_status = status
            result.field_message = message
        return result

    async def run_proactive_alerts(self) -> dict:
        """Same shape as ForecastAlertService.run(): evaluated as an extra step of the existing daily
        batch (src/batch.py), not a new cron. Only alerts when watering is actually needed."""
        fields_evaluated = 0
        alerts_created = 0
        for field in await self.farm_repo.list_all_fields_with_coordinates():
            fields_evaluated += 1
            try:
                et0, rain_forecast_mm = await self._et0_and_rain(field.latitude, field.longitude)
            except Exception:
                logger.exception(f"ET0 computation failed for field {field.id}")
                continue
            if et0 is None:
                continue
            since = utcnow() - timedelta(days=RECENT_IRRIGATION_WINDOW_DAYS)
            events = await self.farm_repo.list_events(
                field.account_id, field_id=field.id, event_type="irrigation", since=since, limit=200
            )
            recent = _irrigation_mm(events, field.area_m2)
            cycles = await self.farm_repo.active_cycles_with_crop(field.account_id)
            field_cycles = [(c, crop) for c, crop in cycles if c.field_id == field.id]
            if not field_cycles:
                continue
            today = date.today()
            kcs = [
                kc_for_stage(
                    crop.kc_initial, crop.kc_mid, crop.kc_late, crop.family,
                    _cycle_progress_pct(cycle, crop, today),
                )
                for cycle, crop in field_cycles
            ]
            field_kc = sum(kcs) / len(kcs)
            net = round(et0 * field_kc - recent, 1)
            status, message = self._status_for(net, rain_forecast_mm)
            if status != "regar":
                continue
            start = utcnow()
            created = await self.alerts.create_system_alert(
                account_id=field.account_id,
                field_id=field.id,
                title=f"{field.name}: falta riego",
                message=message,
                severity="low",
                alert_type="irrigation",
                source="irrigation",
                rule_id="irrigation_deficit",
                recommendations=["Regar hoy, preferentemente temprano a la mañana o al atardecer"],
                metadata={"net_mm": net, "et0_mm": et0, "field_kc": round(field_kc, 2)},
                valid_from=start,
                valid_to=start + timedelta(days=1),
                dedupe_key=f"{field.id}:irrigation_deficit:{today.isoformat()}",
            )
            alerts_created += int(created)
        result = {"fields_evaluated": fields_evaluated, "alerts_created": alerts_created}
        logger.info(f"Irrigation alerts: {result}")
        return result
