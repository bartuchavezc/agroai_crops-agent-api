"""
Zone-level satellite signal (Sentinel-2 via Copernicus): NDVI/NDWI aggregated over a ~500m box around
the field, cross-referenced against THIS field's own recent baseline (not a fixed global threshold) so
the alert reads as "your zone changed" rather than an arbitrary absolute number. On-demand only — no
daily tile-pull batch — matching future.md's own design note on keeping this efficient.
"""
import logging
from datetime import timedelta
from typing import Optional
from uuid import UUID

from src.application.alerts.rules_engine import RulesEngine
from src.application.alerts.service import AlertService
from src.application.farm.schemas import FieldRead
from src.application.farm.service import FarmService
from src.application.storage.service import StorageService
from src.providers.satellite.copernicus import CopernicusAdapter
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .models import ZoneSatelliteReading
from .overlay import draw_boundary_outline
from .repository import ZoneSatelliteRepository
from .schemas import ZoneSatelliteReadingRead, ZoneSatelliteStatus

logger = logging.getLogger(__name__)

# 30 days, not ~10: real testing against Copernicus showed consecutive Sentinel-2 passes can be entirely
# cloud-masked for a given point, so a short window risks "no data" (stats) or a black no-data image
# (render) even when a clear, still-recent pass exists a bit further back. Shared by check_field and
# get_or_render_image so both queries always look at the same period.
_LOOKBACK_DAYS = 30


def _lookback_window() -> tuple[str, str]:
    end = utcnow().date()
    start = end - timedelta(days=_LOOKBACK_DAYS)
    return start.isoformat(), end.isoformat()


def _baseline_ndvi(recent: list[ZoneSatelliteReading]) -> Optional[float]:
    values = [r.ndvi_mean for r in recent if r.ndvi_mean is not None]
    return (sum(values) / len(values)) if values else None


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


class ZoneSatelliteService:
    def __init__(
        self,
        farm_service: FarmService,
        repository: ZoneSatelliteRepository,
        copernicus: CopernicusAdapter,
        storage_service: StorageService,
        alert_service: AlertService,
        rules_engine: RulesEngine,
    ):
        self.farm = farm_service
        self.repo = repository
        self.copernicus = copernicus
        self.storage = storage_service
        self.alerts = alert_service
        self.rules = rules_engine

    async def check_field(self, actor: Actor, field_id: UUID) -> ZoneSatelliteStatus:
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates; satellite status needs one.")

        recent = await self.repo.recent(actor.account_id, field_id, limit=5)
        baseline = _baseline_ndvi(list(recent))

        if not self.copernicus.configured:
            return ZoneSatelliteStatus(
                field_id=field.id,
                field_name=field.name,
                reading=ZoneSatelliteReadingRead.model_validate(recent[0]) if recent else None,
                baseline_ndvi_mean=round(baseline, 3) if baseline is not None else None,
                assessment="El estado satelital de la zona no está disponible: falta configurar las "
                "credenciales de Copernicus (COPERNICUS_CLIENT_ID/COPERNICUS_CLIENT_SECRET).",
                alerts=[],
            )

        start, end = _lookback_window()
        boundary_scoped = bool(field.boundary)
        stats = await self.copernicus.ndvi_stats(field.latitude, field.longitude, start, end, polygon=field.boundary)
        if stats is None:
            return ZoneSatelliteStatus(
                field_id=field.id,
                field_name=field.name,
                reading=ZoneSatelliteReadingRead.model_validate(recent[0]) if recent else None,
                baseline_ndvi_mean=round(baseline, 3) if baseline is not None else None,
                assessment="No se pudo obtener una lectura satelital fresca ahora (nubosidad u otro problema).",
                alerts=[],
                boundary_scoped=boundary_scoped,
            )

        reading = await self.repo.create(
            ZoneSatelliteReading(
                account_id=actor.account_id,
                field_id=field.id,
                captured_at=utcnow(),
                ndvi_mean=stats.ndvi_mean,
                ndvi_min=stats.ndvi_min,
                ndvi_max=stats.ndvi_max,
                ndwi_mean=stats.ndwi_mean,
                pixel_count=stats.pixel_count if boundary_scoped else None,
            )
        )

        rule_ctx = {"ndvi_mean": stats.ndvi_mean, "ndwi_mean": stats.ndwi_mean}
        if baseline is not None and stats.ndvi_mean is not None:
            rule_ctx["ndvi_drop"] = round(baseline - stats.ndvi_mean, 3)
        matches = self.rules.evaluate(rule_ctx, categories=["satellite"])
        for match in matches:
            await self.alerts.create_system_alert(
                account_id=actor.account_id,
                field_id=field.id,
                title=f"{field.name}: {match.message.split('.')[0]}",
                message=match.message,
                severity=match.severity.value,
                alert_type="satellite",
                source="satellite",
                rule_id=match.rule_id,
                recommendations=match.recommendations,
                metadata=rule_ctx,
                dedupe_key=f"{field.id}:{match.rule_id}:{end}",
            )
        assessment = " ".join(m.message for m in matches) or (
            "Sin señales de estrés generalizado en la zona (NDVI/NDWI en rango habitual)."
        )
        return ZoneSatelliteStatus(
            field_id=field.id,
            field_name=field.name,
            reading=ZoneSatelliteReadingRead.model_validate(reading),
            baseline_ndvi_mean=round(baseline, 3) if baseline is not None else None,
            assessment=assessment,
            alerts=[m.message for m in matches],
            boundary_scoped=boundary_scoped,
            pixel_count_caveat=_pixel_count_caveat(stats.pixel_count) if boundary_scoped else None,
        )

    async def get_or_render_image(self, actor: Actor, field_id: UUID, force: bool = False) -> Optional[str]:
        """The field's latest saved NDVI map; renders and persists a new one only if none exists yet (or
        `force=True` for an explicit "Regenerar imagen"). Every successful render is saved as its own
        zone_satellite_readings row (image_identifier set, ndvi/ndwi left null — those come from
        check_field's separate Statistical API call), so "the latest image" survives across requests
        instead of being regenerated — and re-billed a processing credit — on every page view."""
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        if not force:
            existing = await self.repo.latest_image(actor.account_id, field_id)
            if existing:
                return existing
        if not self.copernicus.configured:
            return None
        start, end = _lookback_window()
        png = await self.copernicus.render_map(field.latitude, field.longitude, start, end)
        if not png:
            return None
        image_identifier = await self.storage.save_image(actor, f"satellite-{field.id}.png", png, "image/png")
        await self.repo.create(
            ZoneSatelliteReading(
                account_id=actor.account_id, field_id=field.id, captured_at=utcnow(), image_identifier=image_identifier
            )
        )
        return image_identifier

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
        png = await self.copernicus.true_color_map(field.latitude, field.longitude, start, end)
        if not png:
            return None
        image_identifier = await self.storage.save_image(
            actor, f"boundary-base-{field.id}.png", png, "image/png"
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
