"""
Zone-level soil context from INTA's static national datasets — a real (not photo-guessed) reference for
a field's location. Purely local Postgres lookups (no external API), so cheap enough to compute
synchronously whenever a field's coordinates are set (see FarmService.create_field/update_field).
"""
import logging
from typing import Optional

from .repository import SoilDataRepository
from .schemas import SoilContext

logger = logging.getLogger(__name__)

# The source dataset uses these as its own "not applicable / not determined" placeholders.
_BLANK_VALUES = {"-", "", "No determinada"}


def _clean(value):
    if isinstance(value, str) and value.strip() in _BLANK_VALUES:
        return None
    return value


class SoilContextService:
    def __init__(self, repository: SoilDataRepository):
        self.repo = repository

    async def lookup(self, latitude: float, longitude: float) -> Optional[SoilContext]:
        try:
            unit = await self.repo.find_map_unit(latitude, longitude)
        except Exception:
            logger.exception("Soil map unit lookup failed")
            unit = None
        try:
            ph = await self.repo.nearest_ph(latitude, longitude)
        except Exception:
            logger.exception("Soil pH lookup failed")
            ph = None
        if unit is None and ph is None:
            return None
        unit = unit or {}
        return SoilContext(
            province=_clean(unit.get("provincia")),
            unit_symbol=_clean(unit.get("unit_symbol")),
            soil_order=_clean(unit.get("soil_order")),
            great_group=_clean(unit.get("great_group")),
            subgroup=_clean(unit.get("subgroup")),
            texture_surface=_clean(unit.get("texture_surface")),
            texture_subsoil=_clean(unit.get("texture_subsoil")),
            drainage=_clean(unit.get("drainage")),
            depth_cm=unit.get("depth_cm") or None,
            alkalinity=_clean(unit.get("alkalinity")),
            erosion_hydric=_clean(unit.get("erosion_hydric")),
            erosion_eolic=_clean(unit.get("erosion_eolic")),
            rockiness=_clean(unit.get("rockiness")),
            floodability=_clean(unit.get("floodability")),
            productivity_index=unit.get("productivity_index"),
            dominant_percent=unit.get("dominant_percent"),
            ph_estimate=round(ph, 2) if ph is not None else None,
        )
