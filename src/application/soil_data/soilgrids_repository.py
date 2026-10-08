"""
Point lookup in the SoilGrids tiles stored in the database (see grid_models.py): which pixel holds a coordinate, which
tiles hold that pixel and its neighbours, what the layers say there.

SoilGrids masks urban, water and bare-ice pixels, and a garden in a city is exactly where this app's users are. So when
the pixel of the field has no data, the nearest valid pixel within `SEARCH_RADIUS` pixels (~3 km at 1 km resolution) is
used and the answer says how far it was.
"""
import math
import zlib
from typing import Optional

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .grid_models import SoilGridsGrid, SoilGridsTile
from .schemas import SoilGridsEstimate, SoilLayerEstimate

NODATA = -32768
TILE_SIZE = 128
SEARCH_RADIUS = 3  # pixels
PROPERTIES = ("phh2o", "soc", "nitrogen", "cec")
DEPTHS = ("0-5cm", "5-15cm", "15-30cm")
# SoilGrids stores integers in "mapped units"; dividing by these gives pH, g/kg of carbon and nitrogen and
# cmol(c)/kg of CEC.
D_FACTOR = {"phh2o": 10, "soc": 10, "nitrogen": 100, "cec": 10}
SOURCE = (
    "ISRIC SoilGrids 2.0 (modelo global de suelos, capa de ~1 km): estimación regional, no un análisis de laboratorio"
)


def encode_tile(block: np.ndarray) -> bytes:
    return zlib.compress(np.ascontiguousarray(block, dtype="<i2").tobytes(), 6)


def decode_tile(data: bytes, size: int = TILE_SIZE) -> np.ndarray:
    return np.frombuffer(zlib.decompress(data), dtype="<i2").reshape(size, size)


def pixel_of(grid: SoilGridsGrid, latitude: float, longitude: float) -> Optional[tuple[int, int]]:
    """(row, col) of the pixel holding the point, or None if the point is outside the grid."""
    row = math.floor((grid.max_lat - latitude) / grid.res_lat)
    col = math.floor((longitude - grid.min_lon) / grid.res_lon)
    return (row, col) if 0 <= row < grid.height and 0 <= col < grid.width else None


class SoilGridsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def covers(self, latitude: float, longitude: float) -> bool:
        return await self._grid_for(latitude, longitude) is not None

    async def _grid_for(self, latitude: float, longitude: float) -> Optional[SoilGridsGrid]:
        async with self.session_factory() as session:
            grids = (await session.execute(select(SoilGridsGrid))).scalars().all()
        return next((g for g in grids if pixel_of(g, latitude, longitude) is not None), None)

    async def estimate(self, latitude: float, longitude: float) -> tuple[bool, Optional[SoilGridsEstimate]]:
        """(covered, estimate). `covered` False: no loaded grid contains the point (fall back to another source).
        Covered with no estimate: every pixel around it is masked (open water, say)."""
        grid = await self._grid_for(latitude, longitude)
        if grid is None:
            return False, None
        row0, col0 = pixel_of(grid, latitude, longitude)
        size = grid.tile_size
        r_lo, r_hi = max(row0 - SEARCH_RADIUS, 0), min(row0 + SEARCH_RADIUS, grid.height - 1)
        c_lo, c_hi = max(col0 - SEARCH_RADIUS, 0), min(col0 + SEARCH_RADIUS, grid.width - 1)
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(SoilGridsTile).where(
                    SoilGridsTile.grid == grid.grid,
                    SoilGridsTile.prop.in_(PROPERTIES),
                    SoilGridsTile.depth.in_(DEPTHS),
                    SoilGridsTile.ty.between(r_lo // size, r_hi // size),
                    SoilGridsTile.tx.between(c_lo // size, c_hi // size),
                )
            )).scalars().all()

        # one (rows x cols) window per layer, filled from the tiles that exist (a missing tile is all no-data)
        height, width = r_hi - r_lo + 1, c_hi - c_lo + 1
        windows: dict[tuple[str, str], np.ndarray] = {}
        for tile in rows:
            window = windows.setdefault((tile.prop, tile.depth), np.full((height, width), NODATA, dtype="<i2"))
            block = decode_tile(tile.data, size)
            t_r0, t_c0 = tile.ty * size, tile.tx * size
            rr0, rr1 = max(r_lo, t_r0), min(r_hi + 1, t_r0 + size)
            cc0, cc1 = max(c_lo, t_c0), min(c_hi + 1, t_c0 + size)
            window[rr0 - r_lo:rr1 - r_lo, cc0 - c_lo:cc1 - c_lo] = block[rr0 - t_r0:rr1 - t_r0, cc0 - t_c0:cc1 - t_c0]

        # nearest pixel, by distance, where the topsoil layers all have data (else where the pH at least does)
        top = [windows.get((prop, DEPTHS[0])) for prop in PROPERTIES]
        reference = windows.get(("phh2o", DEPTHS[0]))
        if reference is None:
            return True, None
        has_pH = reference != NODATA
        if all(w is not None for w in top):
            complete = np.logical_and.reduce([w != NODATA for w in top])
            valid = np.argwhere(complete if complete.any() else has_pH)
        else:
            valid = np.argwhere(has_pH)
        if valid.size == 0:
            return True, None
        km_row = grid.res_lat * 111.0
        km_col = grid.res_lon * 111.0 * math.cos(math.radians(latitude))
        dist = np.hypot((valid[:, 0] + r_lo - row0) * km_row, (valid[:, 1] + c_lo - col0) * km_col)
        best = int(np.argmin(dist))
        r, c = valid[best]

        depths: dict[str, SoilLayerEstimate] = {}
        for depth in DEPTHS:
            values = {}
            for prop in PROPERTIES:
                window = windows.get((prop, depth))
                raw = int(window[r, c]) if window is not None else NODATA
                values[prop] = None if raw == NODATA else round(raw / D_FACTOR[prop], 2)
            if any(v is not None for v in values.values()):
                depths[depth] = SoilLayerEstimate(
                    ph=values["phh2o"], organic_carbon_g_kg=values["soc"],
                    nitrogen_g_kg=values["nitrogen"], cec_cmolc_kg=values["cec"],
                )
        if not depths:
            return True, None
        return True, SoilGridsEstimate(
            source=SOURCE, depths=depths, resolution_m=grid.resolution_m,
            distance_km=round(float(dist[best]), 1) if dist[best] > 0 else 0.0,
        )

    # ------------------------------------------------------------ import side

    async def replace_grid(self, grid: SoilGridsGrid, tiles: list[SoilGridsTile]) -> None:
        """Drops the grid (its tiles go with it) and stores the new one."""
        async with self.session_factory() as session:
            await session.execute(text("DELETE FROM soilgrids_grids WHERE grid = :g"), {"g": grid.grid})
            session.add(grid)
            await session.flush()
            for i in range(0, len(tiles), 500):
                session.add_all(tiles[i:i + 500])
                await session.flush()
            await session.commit()
