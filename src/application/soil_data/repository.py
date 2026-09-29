"""
Read-only access to the two static INTA soil reference tables (soil_map_units, soil_ph_points).
Loaded once by src/scripts/import_soil_data.py — never written by the running app.
"""
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MAP_UNIT_COLUMNS = (
    "provincia", "unit_symbol", "unit_type", "productivity_index", "dominant_percent", "position",
    "soil_order", "great_group", "subgroup", "texture_surface", "texture_subsoil", "drainage",
    "depth_cm", "alkalinity", "erosion_hydric", "erosion_eolic", "rockiness", "floodability",
)

# Nearest-pixel search radius: the pH raster is a coarse (~km-scale) grid, so a point with no sample
# within a few km is genuinely outside its covered/valid area, not a lookup bug.
_PH_MAX_DISTANCE_DEG = 0.1


class SoilDataRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def find_map_unit(self, latitude: float, longitude: float) -> Optional[dict]:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT {", ".join(_MAP_UNIT_COLUMNS)}
                    FROM soil_map_units
                    WHERE ST_Contains(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
                    LIMIT 1
                    """
                ),
                {"lat": latitude, "lon": longitude},
            )
            row = result.mappings().first()
            return dict(row) if row else None

    async def nearest_ph(self, latitude: float, longitude: float) -> Optional[float]:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT ph
                    FROM soil_ph_points
                    WHERE ST_DWithin(geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), :max_dist)
                    ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                    LIMIT 1
                    """
                ),
                {"lat": latitude, "lon": longitude, "max_dist": _PH_MAX_DISTANCE_DEG},
            )
            row = result.first()
            return row[0] if row else None
