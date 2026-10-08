from typing import Optional

from pydantic import BaseModel


class SoilLayerEstimate(BaseModel):
    ph: Optional[float] = None
    organic_carbon_g_kg: Optional[float] = None
    nitrogen_g_kg: Optional[float] = None
    cec_cmolc_kg: Optional[float] = None  # cation-exchange capacity


class SoilGridsEstimate(BaseModel):
    """ISRIC SoilGrids 2.0 modelled values at the field's location, by depth. Regional estimates (~250 m, global
    model), not a lab analysis of this field."""

    source: str = "ISRIC SoilGrids 2.0 (modelo global, ~250 m): estimación regional, no un análisis de laboratorio"
    depths: dict[str, SoilLayerEstimate] = {}
    resolution_m: Optional[int] = None
    # Km to the pixel used, when the field's own pixel is masked (urban or water): the nearest valid one stands in.
    distance_km: Optional[float] = None


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
    soilgrids: Optional[SoilGridsEstimate] = None
    # True once SoilGrids has answered for this location (with data or without): don't ask again every time.
    soilgrids_checked: bool = False
