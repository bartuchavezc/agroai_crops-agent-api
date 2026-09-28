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
from src.application.farm.service import FarmService
from src.application.storage.service import StorageService
from src.providers.satellite.copernicus import CopernicusAdapter
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .models import ZoneSatelliteReading
from .repository import ZoneSatelliteRepository
from .schemas import ZoneSatelliteReadingRead, ZoneSatelliteStatus

logger = logging.getLogger(__name__)

_SYSTEM_USER_ID = UUID(int=0)  # batch jobs act on behalf of no real user; user_id is inert for these reads


def _baseline_ndvi(recent: list[ZoneSatelliteReading]) -> Optional[float]:
    values = [r.ndvi_mean for r in recent if r.ndvi_mean is not None]
    return (sum(values) / len(values)) if values else None


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

        end = utcnow().date()
        # 30 days, not ~10: real testing against Copernicus showed consecutive Sentinel-2 passes can be
        # entirely cloud-masked for a given point, so a short window risks "no data" even when a clear,
        # still-recent pass exists a bit further back.
        start = end - timedelta(days=30)
        stats = await self.copernicus.ndvi_stats(field.latitude, field.longitude, start.isoformat(), end.isoformat())
        if stats is None:
            return ZoneSatelliteStatus(
                field_id=field.id,
                field_name=field.name,
                reading=ZoneSatelliteReadingRead.model_validate(recent[0]) if recent else None,
                baseline_ndvi_mean=round(baseline, 3) if baseline is not None else None,
                assessment="No se pudo obtener una lectura satelital fresca ahora (nubosidad u otro problema).",
                alerts=[],
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
                dedupe_key=f"{field.id}:{match.rule_id}:{end.isoformat()}",
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
        )

    async def render_map_image(self, actor: Actor, field_id: UUID) -> Optional[str]:
        """Renders and stores a small true-color PNG of the field's zone; returns its image_identifier, or
        None if Copernicus isn't configured or the call fails (caller decides how to degrade)."""
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError(f"Field '{field.name}' has no coordinates.")
        if not self.copernicus.configured:
            return None
        png = await self.copernicus.render_map(field.latitude, field.longitude)
        if not png:
            return None
        return await self.storage.save_image(actor, f"satellite-{field.id}.png", png, "image/png")

    async def check_after_storm(self, account_id: UUID, field) -> None:
        """Best-effort proactive check for the daily batch (src/batch.py), called only when a heavy-rain
        rule already fired for this field — not a blanket daily pull for every field."""
        try:
            actor = Actor(user_id=_SYSTEM_USER_ID, account_id=account_id, role="system", via="system")
            await self.check_field(actor, field.id)
        except Exception:
            logger.exception(f"Post-storm satellite check failed for field {field.id}")
