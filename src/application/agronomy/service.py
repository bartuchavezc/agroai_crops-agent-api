"""Runs the agronomy models on a real lot or zone: gathers the weather, the soil, the waterings, the readings and the
sun plan, and returns numbers with their inputs and their uncertainty. No decisions here: these are tools the agent
calls and weighs (src/agent/tools/agronomy.py)."""
import logging
import math
from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from src.application.farm.kc_defaults import kc_for_stage
from src.application.farm.schemas import FieldEventCreate
from src.application.farm.shadows import cells_inside
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from . import disease, thermal, water

logger = logging.getLogger(__name__)

MEASUREMENT_KEY = "humedad_suelo"
COVERED_ZONES = ("invernadero",)


def _tz(actor: Actor) -> ZoneInfo:
    try:
        return ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("America/Argentina/Buenos_Aires")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _local_today(actor: Actor) -> date:
    return utcnow().astimezone(_tz(actor)).date()


def _polygon_of(obj) -> Optional[list[tuple[float, float]]]:
    if obj.points and len(obj.points) >= 3:
        return [tuple(p) for p in obj.points]
    radius = obj.radius_m or 0.5
    return [(obj.x_m + radius * math.cos(a), obj.y_m + radius * math.sin(a))
            for a in (i * 2 * math.pi / 16 for i in range(16))]


class AgronomyModels:
    def __init__(self, farm_service, weather_service):
        self.farm = farm_service
        self.weather = weather_service

    # ---------- shared ----------

    async def _lot_context(self, actor: Actor, lot_id: UUID):
        lot = await self.farm.get_lot(actor, lot_id)
        field = await self.farm.get_field(actor, lot.field_id)
        crop = await self.farm.get_crop_master(actor, lot.crop_master_id)
        zones = [await self.farm.get_zone(actor, z) for z in lot.zone_ids]
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates: the models need its location.")
        return lot, field, crop, zones

    # ---------- water ----------

    def _texture(self, field, zone) -> tuple[str, str]:
        if zone is not None and zone.type in ("maceta", "hidroponia"):
            return "sustrato", "sustrato de maceta" if zone.type == "maceta" else "sustrato"
        if zone is not None and zone.soil and zone.soil.notes and "sustrato" in zone.soil.notes.lower():
            return "sustrato", "sustrato (nota de la zona)"
        soil = field.soil_context
        found = water.texture_from_text(soil.texture_surface if soil else None) or \
            water.texture_from_text(field.soil_type)
        if found:
            return found, f"textura {found.replace('_', ' ')} (mapa de suelos / campo)"
        return "franco", "textura franca supuesta (sin dato de suelo)"

    async def water_balance(self, actor: Actor, lot_id: UUID, days: int = 21) -> dict:
        """Root-zone water of a lot (its first zone), from the last `days` of ET0, rain, logged waterings and the
        soil readings, with the crop's Kc for its stage."""
        lot, field, crop, zones = await self._lot_context(actor, lot_id)
        zone = zones[0] if zones else None
        texture, texture_note = self._texture(field, zone)
        zone_type = zone.type if zone else "tierra_directa"
        root_depth = water.ROOT_DEPTH_BY_ZONE.get(zone_type, 0.4)
        p = water.P_BY_CROP.get(thermal.crop_key(crop.name), 0.5)
        today = _local_today(actor)
        weather = await self.weather.open_meteo.daily_window(field.latitude, field.longitude, past_days=days,
                                                             forecast_days=1)
        if not weather:
            raise InvalidInputError("No weather data for this field right now.")
        since = datetime.combine(today - timedelta(days=days), time.min).replace(tzinfo=ZoneInfo("UTC"))
        events = await self.farm.list_events(actor, field_id=field.id, since=since, limit=500)
        area = (zone.area_m2 if zone else None) or field.area_m2
        irrigation: dict[str, float] = {}
        readings: dict[str, water.Reading] = {}
        for e in events:
            reached = lot.id in e.lot_ids or (zone is not None and e.zone_id == zone.id) or \
                (e.zone_id is None and not e.lot_ids)
            if not reached:
                continue
            day = e.occurred_at.date().isoformat()
            if e.type == "irrigation" and e.outcome == "done" and e.quantity:
                unit = (e.unit or "").lower()
                mm = e.quantity if unit in ("mm", "milimetros", "milímetros") else \
                    (e.quantity / area if area else 0.0)
                irrigation[day] = irrigation.get(day, 0.0) + mm
            measurement = (e.data or {}).get("measurement")
            if measurement == MEASUREMENT_KEY:
                readings[day] = water.Reading(vwc_percent=(e.data or {}).get("vwc_percent"),
                                              feel=(e.data or {}).get("feel"))
        progress = 100 * (today - lot.planting_date).days / crop.growth_period_days \
            if lot.planting_date and crop.growth_period_days else 50.0
        kc = kc_for_stage(crop.kc_initial, crop.kc_mid, crop.kc_late, crop.family, max(0.0, min(100.0, progress)))
        series = [
            water.WaterDay(day=date.fromisoformat(d["date"]), et0_mm=d["et0_mm"] or 0.0,
                           rain_mm=d["precipitation_mm"] or 0.0, irrigation_mm=irrigation.get(d["date"], 0.0),
                           reading=readings.get(d["date"]))
            for d in weather if not d.get("forecast")
        ]
        result = water.simulate(series, kc=kc, texture=texture, root_depth_m=root_depth, p=p,
                                covered=zone_type in COVERED_ZONES)
        irrigation_setup = (zone.irrigation if zone and zone.irrigation else field.irrigation)
        return {
            "lot": lot.label, "zone": zone.label if zone else None, "status": result.status,
            "available_water_percent": result.moisture_percent_of_available,
            "depletion_mm": result.depletion_mm, "uncertainty_mm": result.uncertainty_mm,
            "taw_mm": result.taw_mm, "raw_mm": result.raw_mm, "etc_mm_today": result.etc_mm_today,
            "days_to_stress": result.days_to_raw, "days_since_calibration": result.days_since_calibration,
            "kc": round(kc, 2), "root_depth_m": root_depth, "p": p,
            "assumptions": [texture_note, f"raíces hasta {int(root_depth * 100)} cm ({zone_type})",
                            "bajo techo: la lluvia no cuenta" if zone_type in COVERED_ZONES else
                            "lluvia efectiva: se descartan lluvias < 2 mm",
                            "riegos sin cantidad no suman" if any(
                                e.type == "irrigation" and not e.quantity for e in events) else None,
                            f"riego: {irrigation_setup.system}" if irrigation_setup and irrigation_setup.system
                            else "sistema de riego no declarado"],
            "calibrate_with": "una lectura de humedad a la profundidad de raíces (sensor o tacto) la recalibra",
            "series": result.series,
        }

    async def record_soil_moisture(self, actor: Actor, lot_id: UUID, vwc_percent: Optional[float],
                                   feel: Optional[str], depth_cm: Optional[float], notes: Optional[str]) -> dict:
        if vwc_percent is None and feel not in water.FEEL:
            raise InvalidInputError(f"Give vwc_percent (a probe) or feel: {', '.join(water.FEEL)}.")
        lot = await self.farm.get_lot(actor, lot_id)
        event = await self.farm.create_event(actor, FieldEventCreate(
            field_id=lot.field_id, zone_id=lot.zone_id, lot_ids=[lot.id], type="inspection",
            notes=notes or f"Humedad de suelo{f' a {depth_cm:g} cm' if depth_cm else ''}: "
            + (f"{vwc_percent:g} %" if vwc_percent is not None else feel.replace("_", " ")),
            data={"measurement": MEASUREMENT_KEY, "vwc_percent": vwc_percent, "feel": feel, "depth_cm": depth_cm},
        ))
        return {"event_id": str(event.id)}

    # ---------- thermal time ----------

    async def thermal_time(self, actor: Actor, lot_id: UUID) -> dict:
        lot, field, crop, zones = await self._lot_context(actor, lot_id)
        start = lot.transplant_date or lot.planting_date
        if start is None:
            raise InvalidInputError("The lot has no planting date: thermal time counts from it.")
        today = _local_today(actor)
        past = max(0, (today - start).days)
        weather = await self.weather.open_meteo.daily_window(field.latitude, field.longitude,
                                                             past_days=min(past, 92), forecast_days=7)
        tbase, tupper, to_harvest, source = thermal.thermal_params(
            crop.name, getattr(crop, "t_base_c", None), getattr(crop, "t_upper_c", None),
            getattr(crop, "gdd_to_maturity", None),
        )
        days = [{"tmin": d["temp_min_c"], "tmax": d["temp_max_c"]} for d in weather
                if not d.get("forecast") and d["date"] >= start.isoformat()]
        forecast = [{"tmin": d["temp_min_c"], "tmax": d["temp_max_c"]} for d in weather if d.get("forecast")]
        result = thermal.accumulate(days, tbase, tupper, to_harvest, forecast, source)
        light = None
        if zones:
            try:
                light = await self.zone_light(actor, zones[0].id)
            except InvalidInputError:
                light = None
        out = {
            "lot": lot.label, "crop": crop.name, "since": start.isoformat(),
            "counted_from": "trasplante" if lot.transplant_date else "siembra",
            "gdd": result.gdd, "gdd_last_7_days": result.gdd_last_7, "days": result.days,
            "tbase_c": tbase, "tupper_c": tupper, "params": source,
            "gdd_to_first_harvest": to_harvest, "progress_percent": result.progress_percent,
            "projected_days_to_harvest": result.projected_days_left,
            "note": "Orientativo: variedad y manejo cambian mucho el total; contrastalo con lo observado.",
        }
        if past > 92:
            out["note"] += " Solo se cuentan los últimos 92 días."
        if light and light.get("relative_light") is not None and light["relative_light"] < 0.75:
            out["light_note"] = (f"La zona recibe {light['zone_sun_hours']} h de sol directo contra "
                                 f"{light['open_sky_hours']} h a cielo abierto: con menos luz el avance suele ser "
                                 "más lento que lo que dicen los grados-día.")
        return out

    # ---------- light ----------

    async def zone_light(self, actor: Actor, zone_id: UUID, season: Optional[str] = None) -> dict:
        """Hours of direct sun on a zone, from the field's plan and the shadow model, against open sky."""
        zone = await self.farm.get_zone(actor, zone_id)
        field = await self.farm.get_field(actor, zone.field_id)
        season = season or thermal.season_for(_local_today(actor), field.latitude)
        sun = await self.farm.sun_map(actor, field.id, season)
        obj = next((o for o in field.layout_objects if o.id == zone.layout_object_id), None) \
            if zone.layout_object_id else None
        hours = None
        if obj is not None:
            cells = cells_inside([(c.x, c.y, c.hours) for c in sun.cells], _polygon_of(obj))
            if cells:
                hours = round(sum(c[2] for c in cells) / len(cells), 1)
        source = "zona dibujada en el plano"
        if hours is None:
            hours = sun.plot_mean_hours or sun.mean_hours
            source = "promedio del campo (la zona no está dibujada en el plano)"
        return {
            "zone": zone.label, "season": season, "zone_sun_hours": hours, "open_sky_hours": sun.max_hours,
            "relative_light": round(hours / sun.max_hours, 2) if sun.max_hours else None, "source": source,
            "covered": zone.type in COVERED_ZONES,
        }

    # ---------- disease risk ----------

    async def disease_risk(self, actor: Actor, field_id: UUID, crop_name: Optional[str] = None,
                           models: Optional[list[str]] = None, past_days: int = 7, forecast_days: int = 3) -> dict:
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        chosen = models or list(disease.BY_CROP.get(thermal.crop_key(crop_name or ""), ())) or \
            ["tomcast", "blitecast", "oidio", "mildiu"]
        hours = await self.weather.open_meteo.hourly_window(field.latitude, field.longitude, past_days,
                                                            forecast_days)
        if not hours:
            raise InvalidInputError("No hourly weather for this field right now.")
        now = utcnow().astimezone(_tz(actor)).strftime("%Y-%m-%dT%H:00")
        series = [disease.Hour(h.time, h.temperature, h.humidity) for h in hours]
        past = [h for h in series if h.time <= now]
        risks = disease.run(past, chosen)
        ahead = disease.run(series, chosen)
        return {
            "field": field.name, "crop": crop_name, "models": chosen,
            "risks": [{"disease": r.disease, "model": r.model, "level": r.level, "index": r.index,
                       "detail": r.detail, "with_forecast": {"level": f.level, "index": f.index},
                       "daily": r.daily} for r, f in zip(risks, ahead, strict=True)],
            "inputs": f"Open-Meteo horario, {past_days} días atrás + {forecast_days} de pronóstico; hoja mojada "
                      "estimada como HR ≥ 90 %",
            "note": "Bajo cubierta la humedad real suele ser mayor que la del modelo: tomalo como piso.",
        }
