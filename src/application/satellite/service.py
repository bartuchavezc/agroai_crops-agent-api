"""
Field-level satellite signal (Copernicus): a time series per field — Sentinel-2 NDVI/NDRE/NDMI/EVI/NDWI
plus Sentinel-1 radar for cloudy stretches — read against THIS field's own history (its normal for the same
week in previous years, last year, its season curve) so an alert reads as "this field is doing worse than
usual" instead of an arbitrary absolute number.

The series is kept by SatelliteIngestService (daily batch + backfill, see src/batch.py). User-facing reads
only call Copernicus when the stored series is stale, and within the on-demand share of the monthly
processing-unit budget.
"""
import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from src.application.alerts.rules_engine import RulesEngine
from src.application.alerts.service import AlertService
from src.application.farm.models import ACTIVE_CROP_CYCLE_STATUSES
from src.application.farm.repository import FarmRepository
from src.application.farm.schemas import FieldRead
from src.application.farm.service import FarmService
from src.application.storage.service import StorageService
from src.providers.satellite.copernicus import CopernicusAdapter
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from . import analytics
from .ingest import KIND_ON_DEMAND, BudgetExceeded, SatelliteIngestService
from .models import SOURCE_S1, SOURCE_S2, ZoneSatelliteReading
from .overlay import draw_boundary_outline
from .repository import SatelliteSeriesRepository, ZoneSatelliteRepository
from .schemas import ZoneSatelliteReadingRead, ZoneSatelliteStatus

logger = logging.getLogger(__name__)

# 30 days, not ~10: real testing against Copernicus showed consecutive Sentinel-2 passes can be entirely
# cloud-masked for a given point, so a short window risks a black no-data image even when a clear,
# still-recent pass exists a bit further back.
_LOOKBACK_DAYS = 30
# First on-demand sync of a field fetches only the current season (fast); the batch completes the history.
_ON_DEMAND_HISTORY_YEARS = 1
# No alerts from a series whose last clear pass is older than this: it would describe a stale situation.
_ALERT_MAX_AGE_DAYS = 20

_STAGE_LABELS = {
    "sin_datos": "sin datos suficientes de la temporada",
    "sin_ciclo_marcado": "sin un ciclo de crecimiento marcado (pastura/perenne, suelo desnudo o datos escasos)",
    "pre_brote": "antes del brote",
    "crecimiento": "en crecimiento",
    "pico": "cerca del pico de vegetación",
    "caida": "en caída (senescencia/madurez)",
    "fin_de_ciclo": "fin de ciclo",
}


def reuse_hours() -> float:
    """How old the stored series can be before a user-facing read syncs it again from Copernicus (each call spends
    processing credits). `SATELLITE_MAX_AGE_HOURS`, default 12; Sentinel-2 revisits every ~5 days."""
    try:
        return float(os.environ.get("SATELLITE_MAX_AGE_HOURS", "12"))
    except ValueError:
        return 12.0


def _lookback_window() -> tuple[str, str]:
    end = utcnow().date()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    return start.isoformat(), end.isoformat()


def _pixel_count_caveat(pixel_count: Optional[int]) -> Optional[str]:
    if pixel_count is None:
        return None
    if pixel_count <= 1:
        return (
            "Tu campo es muy chico para distinguirlo de la zona con precisión (menos de un píxel "
            "Sentinel-2 completo, 10m x 10m, dentro del borde que marcaste)."
        )
    if pixel_count <= 8:
        return f"Estimado sobre pocos píxeles Sentinel-2 ({pixel_count}, de 10m c/u) — tomalo como orientativo."
    return f"Estimado sobre {pixel_count} píxeles Sentinel-2 (10m c/u) dentro de tu campo."


def rule_context(analysis: analytics.SeriesAnalysis) -> dict[str, Any]:
    """Flatten the analysis into the satellite rules' context (see RulesEngine._load_satellite_rules)."""
    ctx: dict[str, Any] = {}
    for metric in ("ndvi", "ndmi"):
        status = analysis.status(metric) or {}
        for key in ("vs_normal", "normal_years", "below_p10_streak", "vs_last_year", "trend_15d", "normal_trend_15d"):
            if status.get(key) is not None:
                ctx[f"{metric}_{key}"] = status[key]
    trend = ctx.get("ndvi_trend_15d")
    if trend is not None and trend < 0:
        ctx["ndvi_drop_15d"] = round(-trend, 3)
    if analysis.last_pass:
        ctx["ndvi_mean"] = analysis.last_pass.get("ndvi_mean")
        ctx["ndwi_mean"] = analysis.last_pass.get("ndwi_mean")
    return ctx


def summarize(analysis: analytics.SeriesAnalysis) -> str:
    """One plain-Spanish sentence of where the field stands, for the status card / the agent."""
    if not analysis.has_data:
        return "Todavía no hay una serie satelital con pasadas sin nubes para este campo."
    parts = []
    ndvi = analysis.status("ndvi") or {}
    last = analysis.last_pass or {}
    parts.append(
        f"Última pasada sin nubes: {last.get('date')} (hace {analysis.days_since_last_pass} días), "
        f"NDVI {ndvi.get('value', last.get('ndvi_mean'))}."
    )
    stage = (analysis.phenology or {}).get("stage")
    if stage and stage != "sin_datos":
        parts.append(f"Etapa: {_STAGE_LABELS.get(stage, stage)}.")
    if ndvi.get("position"):
        parts.append(
            f"Respecto de lo normal para esta época ({ndvi['normal_years']} años): "
            f"{ndvi['position'].replace('_', ' ')} ({ndvi['vs_normal']:+.2f})."
        )
    if ndvi.get("vs_last_year") is not None:
        parts.append(f"Contra el año pasado: {ndvi['vs_last_year']:+.2f}.")
    return " ".join(parts)


class ZoneSatelliteService:
    def __init__(
        self,
        farm_service: FarmService,
        farm_repository: FarmRepository,
        repository: ZoneSatelliteRepository,
        series_repository: SatelliteSeriesRepository,
        ingest: SatelliteIngestService,
        copernicus: CopernicusAdapter,
        storage_service: StorageService,
        alert_service: AlertService,
        rules_engine: RulesEngine,
        min_valid_fraction: float = 0.6,
    ):
        self.farm = farm_service
        self.farm_repo = farm_repository
        self.repo = repository
        self.series_repo = series_repository
        self.ingest = ingest
        self.copernicus = copernicus
        self.storage = storage_service
        self.alerts = alert_service
        self.rules = rules_engine
        self.min_valid_fraction = float(min_valid_fraction)

    # ------------------------------------------------------------ series

    async def refresh_if_stale(self, field: Any) -> Optional[str]:
        """On-demand sync when the stored series is older than `reuse_hours()`. Returns a note for the
        user when the refresh couldn't happen (budget/credentials), None otherwise."""
        if not self.copernicus.configured:
            return "Falta configurar las credenciales de Copernicus (COPERNICUS_CLIENT_ID/COPERNICUS_CLIENT_SECRET)."
        state = await self.series_repo.get_sync(field.id, SOURCE_S2)
        geometry = self.copernicus.geometry_hash(field.latitude, field.longitude, field.boundary)
        fresh = state and utcnow() - state.last_synced_at < timedelta(hours=reuse_hours())
        if state and state.geometry_hash == geometry and fresh:
            return None
        try:
            await self.ingest.sync_field(field, kind=KIND_ON_DEMAND, history_years=_ON_DEMAND_HISTORY_YEARS)
        except BudgetExceeded:
            return "Se alcanzó el cupo mensual de consultas a Copernicus; se muestran los últimos datos guardados."
        except Exception:  # noqa: BLE001 - the stored series is still worth showing
            logger.exception(f"On-demand satellite sync failed for field {field.id}")
            return "No se pudo actualizar la serie satelital ahora; se muestran los últimos datos guardados."
        return None

    async def _season(self, account_id: UUID, field_id: UUID) -> Optional[tuple[date, Optional[date]]]:
        cycles = await self.farm_repo.list_crop_cycles(
            account_id, field_id=field_id, statuses=ACTIVE_CROP_CYCLE_STATUSES
        )
        for cycle in cycles:
            if cycle.planting_date:
                return cycle.planting_date, cycle.actual_harvest_date or cycle.expected_harvest_date
        return None

    async def analyze(self, account_id: UUID, field: Any) -> analytics.SeriesAnalysis:
        today = utcnow().date()
        s2 = await self.series_repo.series(account_id, field.id, SOURCE_S2)
        s1 = await self.series_repo.series(account_id, field.id, SOURCE_S1, since=today - timedelta(days=120))
        season = await self._season(account_id, field.id)
        return analytics.analyze(s2, s1, today, season=season, min_valid_fraction=self.min_valid_fraction)

    async def evaluate_alerts(self, account_id: UUID, field: Any, analysis: analytics.SeriesAnalysis) -> list:
        """Run the satellite rules on a fresh-enough analysis and persist matches as system alerts, at most
        once per rule per field per ISO week of the observation (a weekly cadence, not one per pass)."""
        if not analysis.has_data or (analysis.days_since_last_pass or 0) > _ALERT_MAX_AGE_DAYS:
            return []
        ctx = rule_context(analysis)
        matches = self.rules.evaluate(ctx, categories=["satellite"])
        last_date = date.fromisoformat(str(analysis.last_pass["date"]))
        year, week, _ = last_date.isocalendar()
        for match in matches:
            await self.alerts.create_system_alert(
                account_id=account_id,
                field_id=field.id,
                title=f"{field.name}: {match.message.split(':')[0].split('.')[0]}",
                message=match.message,
                severity=match.severity.value,
                alert_type="satellite",
                source="satellite",
                rule_id=match.rule_id,
                recommendations=match.recommendations,
                metadata={**ctx, "observed_on": last_date.isoformat()},
                dedupe_key=f"{field.id}:{match.rule_id}:{year}-W{week:02d}",
            )
        return matches

    async def run_alerts_for_field(self, field: Any) -> int:
        """Batch entry point (no actor): analyze the stored series and raise alerts."""
        analysis = await self.analyze(field.account_id, field)
        return len(await self.evaluate_alerts(field.account_id, field, analysis))

    async def check_field(self, actor: Actor, field_id: UUID, refresh: bool = True) -> ZoneSatelliteStatus:
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates; satellite status needs one.")
        note = await self.refresh_if_stale(field) if refresh else None
        analysis = await self.analyze(actor.account_id, field)
        matches = await self.evaluate_alerts(actor.account_id, field, analysis)

        reading = None
        if analysis.has_data:
            s2 = await self.series_repo.series(
                actor.account_id, field.id, SOURCE_S2, since=date.fromisoformat(str(analysis.last_pass["date"]))
            )
            if s2:
                obs = s2[0]
                reading = ZoneSatelliteReadingRead(
                    id=obs.id,
                    field_id=field.id,
                    captured_at=datetime.combine(obs.observed_on, time(), tzinfo=timezone.utc),
                    ndvi_mean=obs.ndvi_mean,
                    ndvi_min=obs.ndvi_min,
                    ndvi_max=obs.ndvi_max,
                    ndwi_mean=obs.ndwi_mean,
                    pixel_count=obs.valid_pixels if field.boundary else None,
                    source=SOURCE_S2,
                )
        ndvi = analysis.status("ndvi") or {}
        assessment = " ".join(
            part for part in (
                summarize(analysis),
                " ".join(m.message for m in matches) or (
                    "Sin señales de estrés respecto de la historia del campo." if analysis.has_data else ""
                ),
                note or "",
            ) if part
        )
        boundary_scoped = bool(field.boundary)
        return ZoneSatelliteStatus(
            field_id=field.id,
            field_name=field.name,
            reading=reading,
            baseline_ndvi_mean=ndvi.get("normal_p50") if (ndvi.get("normal_years") or 0) >= 2 else None,
            assessment=assessment,
            alerts=[m.message for m in matches],
            boundary_scoped=boundary_scoped,
            pixel_count_caveat=_pixel_count_caveat(reading.pixel_count) if reading and boundary_scoped else None,
            analysis=analysis.to_dict(),
        )

    async def series(
        self, actor: Actor, field_id: UUID, metric: str = "ndvi", since: Optional[date] = None
    ) -> dict:
        """Raw passes + weekly smoothed/normal/last-year table for one metric — the data behind a chart or
        the agent's series tool. Reads the stored series only (no Copernicus call)."""
        if metric not in analytics.METRICS:
            raise InvalidInputError(f"Unknown metric '{metric}'. Use one of: {', '.join(analytics.METRICS)}.")
        field = await self.farm.get_field(actor, field_id)
        today = utcnow().date()
        since = since or today - timedelta(days=365)
        s2 = await self.series_repo.series(actor.account_id, field.id, SOURCE_S2)
        s1 = await self.series_repo.series(actor.account_id, field.id, SOURCE_S1, since=since)
        return {
            "field_id": str(field.id),
            "field_name": field.name,
            "metric": metric,
            "since": since.isoformat(),
            "history_from": s2[0].observed_on.isoformat() if s2 else None,
            "weekly": analytics.weekly_table(s2, metric, since, today, self.min_valid_fraction),
            "passes": analytics.raw_points(
                [o for o in s2 if o.observed_on >= since], [f"{metric}_mean"]
            ),
            "radar_passes": analytics.raw_points(s1, ["vh_vv_db", "rvi_mean"]),
        }

    async def sync(self, actor: Actor, field_id: UUID) -> dict:
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        if not self.copernicus.configured:
            return {"synced": False, "message": "Copernicus credentials not configured."}
        try:
            report = await self.ingest.sync_field(field, kind=KIND_ON_DEMAND, history_years=_ON_DEMAND_HISTORY_YEARS)
        except BudgetExceeded as e:
            return {"synced": False, "message": str(e)}
        return {"synced": True, **report.to_dict()}

    async def compare_fields(self, actor: Actor) -> list[dict]:
        """Every field of the account read against its own history (stored data only), most anomalous
        first — "which of my fields is doing worst relative to what's normal for it"."""
        rows = []
        for field in await self.farm.list_fields(actor):
            if field.latitude is None or field.longitude is None:
                continue
            analysis = await self.analyze(actor.account_id, field)
            ndvi = analysis.status("ndvi") or {}
            rows.append(
                {
                    "field": field.name,
                    "last_pass": (analysis.last_pass or {}).get("date"),
                    "days_since_last_pass": analysis.days_since_last_pass,
                    "ndvi": ndvi.get("value"),
                    "vs_normal": ndvi.get("vs_normal"),
                    "position": ndvi.get("position"),
                    "normal_years": ndvi.get("normal_years"),
                    "vs_last_year": ndvi.get("vs_last_year"),
                    "trend_15d": ndvi.get("trend_15d"),
                    "stage": (analysis.phenology or {}).get("stage"),
                    "has_data": analysis.has_data,
                }
            )
        def key(row: dict) -> tuple:
            score = row["vs_normal"] if row["vs_normal"] is not None else row["vs_last_year"]
            return (score is None, score if score is not None else 0.0)
        return sorted(rows, key=key)

    # ------------------------------------------------------------ images

    async def get_or_render_image(self, actor: Actor, field_id: UUID, force: bool = False) -> Optional[str]:
        """The field's latest saved NDVI map; renders and persists a new one only if none exists yet (or
        `force=True` for an explicit "Regenerar imagen"). Every successful render is saved as its own
        zone_satellite_readings row (image_identifier set; the numbers live in the field's series), so "the
        latest image" survives across requests instead of being regenerated — and re-billed processing
        units — on every page view."""
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        if not force:
            existing = await self.repo.latest_image(actor.account_id, field_id)
            if existing:
                return existing
        if not self.copernicus.configured:
            return None
        try:
            if await self.ingest.budget_left(KIND_ON_DEMAND) <= 0:
                return None
        except Exception:  # noqa: BLE001 - the budget table being unreachable shouldn't block the map
            logger.exception("Could not read Copernicus usage")
        start, end = _lookback_window()
        image = await self.copernicus.render_map(field.latitude, field.longitude, start, end)
        await self._record_image_usage(image)
        if not image:
            return None
        image_identifier = await self.storage.save_image(
            actor, f"satellite-{field.id}.png", image.png, "image/png"
        )
        await self.repo.create(
            ZoneSatelliteReading(
                account_id=actor.account_id, field_id=field.id, captured_at=utcnow(), image_identifier=image_identifier
            )
        )
        return image_identifier

    async def _record_image_usage(self, image) -> None:
        try:
            await self.series_repo.add_usage(KIND_ON_DEMAND, image.processing_units if image else None)
        except Exception:  # noqa: BLE001
            logger.exception("Could not record Copernicus usage")

    async def zone_bbox(self, actor: Actor, field_id: UUID) -> Optional[list[float]]:
        """The lat/lon box [minlon, minlat, maxlon, maxlat] every zone image covers, so the frontend can
        overlay the field's boundary on it."""
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            return None
        return self.copernicus.bbox_for(field.latitude, field.longitude)

    async def render_delineation_base(self, actor: Actor, field_id: UUID) -> Optional[tuple[str, list[float]]]:
        """A fresh true-color image (not NDVI-colorized) for the user to draw their field's boundary over,
        plus the exact lat/lon box it covers (so the frontend can convert clicked points back to lat/lon).
        Never persisted as a zone_satellite_readings row — it's a disposable working image, not a
        "reading"; only StorageService's serving plumbing (GET /upload/image/{id}) is reused."""
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        if not self.copernicus.configured:
            return None
        start, end = _lookback_window()
        image = await self.copernicus.true_color_map(field.latitude, field.longitude, start, end)
        await self._record_image_usage(image)
        if not image:
            return None
        image_identifier = await self.storage.save_image(
            actor, f"boundary-base-{field.id}.png", image.png, "image/png"
        )
        return image_identifier, self.copernicus.bbox_for(field.latitude, field.longitude)

    async def image_bytes_for_model(
        self, actor: Actor, image_identifier: str, max_side: int = 1024, field: Optional[FieldRead] = None
    ) -> tuple[bytes, str]:
        """Passthrough to StorageService, kept here so callers outside the application layer (agent tools)
        don't need StorageService wired in just for this one read. When `field` has a drawn boundary, the
        outline is composited on top (in-memory only, never written back to storage) so the vision model
        can tell the user's actual field apart from the surrounding ~500m zone context."""
        raw, mime = await self.storage.get_image_for_model(actor, image_identifier, max_side)
        if field and field.boundary and field.latitude is not None and field.longitude is not None:
            bbox = self.copernicus.bbox_for(field.latitude, field.longitude)
            raw = draw_boundary_outline(raw, field.boundary, bbox)
            mime = "image/png"
        return raw, mime
