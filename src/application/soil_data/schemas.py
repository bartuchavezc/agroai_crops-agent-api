from typing import Optional

from pydantic import BaseModel


class SoilContext(BaseModel):
    """A field's official soil read, from INTA's national datasets (not a photo guess) — a zone signal
    (1:500.000 map units, ~km-scale pH raster), not per-plant precision."""

    source: str = "INTA - Suelos de la República Argentina 1:500.000 + Mapa de pH 0-30cm"
    unit_symbol: Optional[str] = None
    province: Optional[str] = None
    soil_order: Optional[str] = None
    great_group: Optional[str] = None
    subgroup: Optional[str] = None
    texture_surface: Optional[str] = None
    texture_subsoil: Optional[str] = None
    drainage: Optional[str] = None
    depth_cm: Optional[float] = None
    alkalinity: Optional[str] = None
    erosion_hydric: Optional[str] = None
    erosion_eolic: Optional[str] = None
    rockiness: Optional[str] = None
    floodability: Optional[str] = None
    productivity_index: Optional[float] = None
    dominant_percent: Optional[float] = None
    ph_estimate: Optional[float] = None
