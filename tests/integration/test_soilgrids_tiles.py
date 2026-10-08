"""SoilGrids stored in our database as georeferenced tiles: the importer's tiling, the pixel maths, the neighbour search
for masked (urban) pixels, and what happens outside the loaded grids (nothing is invented)."""
from unittest.mock import patch

import numpy as np

from src.application.soil_data.grid_models import SoilGridsGrid, SoilGridsTile
from src.application.soil_data.soilgrids_repository import (
    DEPTHS, NODATA, PROPERTIES, SoilGridsRepository, decode_tile, encode_tile, pixel_of,
)
from src.scripts.import_soilgrids import tiles_of

TILE = 128
H, W = 200, 300  # not a multiple of the tile: the edges get padded
# A 1 km grid whose upper-left corner is (-101.0, 21.0): pixel (r, c) is at lat 21 - r*0.009, lon -101 + c*0.009.
GRID = SoilGridsGrid(
    grid="testland", min_lon=-101.0, max_lat=21.0, res_lon=0.009, res_lat=0.009,
    width=W, height=H, tile_size=TILE, resolution_m=1000,
)


def _layers(values: dict[str, int], masked: list[tuple[int, int]] = ()):
    """Every property/depth: a constant integer, with some pixels masked."""
    out = {}
    for prop in PROPERTIES:
        array = np.full((H, W), values[prop], dtype="<i2")
        for r, c in masked:
            array[r, c] = NODATA
        out[prop] = array
    return out


def _rows(layers) -> list[SoilGridsTile]:
    return [
        SoilGridsTile(grid="testland", prop=prop, depth=depth, tx=tx, ty=ty, data=encode_tile(block))
        for prop, array in layers.items() for depth in DEPTHS for tx, ty, block in tiles_of(array)
    ]


async def _load(container, layers):
    repo = SoilGridsRepository(container.db_session_factory())
    await repo.replace_grid(SoilGridsGrid(**{c.name: getattr(GRID, c.name) for c in SoilGridsGrid.__table__.columns}),
                            _rows(layers))
    return repo


def test_tiles_are_lossless_skip_empty_blocks_and_pad_the_edges():
    array = np.full((H, W), NODATA, dtype="<i2")
    array[130, 140] = 75  # the only valid pixel -> only its block is kept
    blocks = list(tiles_of(array))
    assert [(tx, ty) for tx, ty, _ in blocks] == [(1, 1)]
    restored = decode_tile(encode_tile(blocks[0][2]))
    assert restored.shape == (TILE, TILE) and restored[130 - 128, 140 - 128] == 75
    assert pixel_of(GRID, 20.9, -100.9) == (11, 11) and pixel_of(GRID, 22.0, -100.9) is None


async def test_point_lookup_converts_mapped_units_and_reports_the_grid_resolution(container):
    repo = await _load(container, _layers({"phh2o": 75, "soc": 167, "nitrogen": 168, "cec": 282}))
    covered, estimate = await repo.estimate(20.5, -100.5)
    assert covered is True and estimate.resolution_m == 1000 and estimate.distance_km == 0.0
    top = estimate.depths["0-5cm"]
    assert (top.ph, top.organic_carbon_g_kg, top.nitrogen_g_kg, top.cec_cmolc_kg) == (7.5, 16.7, 1.68, 28.2)
    assert set(estimate.depths) == set(DEPTHS)
    assert await repo.estimate(25.0, -100.5) == (False, None)  # no loaded grid holds it


async def test_masked_pixel_uses_the_nearest_valid_neighbour_and_says_how_far(container):
    r, c = 55, 140  # across a tile boundary at c=128 is also in reach
    repo = await _load(container, _layers({"phh2o": 70, "soc": 100, "nitrogen": 90, "cec": 200}, masked=[(r, c)]))
    lat, lon = 21.0 - (r + 0.5) * 0.009, -101.0 + (c + 0.5) * 0.009
    covered, estimate = await repo.estimate(lat, lon)
    assert covered and estimate.distance_km is not None and 0.8 <= estimate.distance_km <= 1.2  # the next pixel over
    assert estimate.depths["0-5cm"].ph == 7.0

    everything_masked = [(rr, cc) for rr in range(r - 3, r + 4) for cc in range(c - 3, c + 4)]
    layers = _layers({"phh2o": 70, "soc": 100, "nitrogen": 90, "cec": 200}, masked=everything_masked)
    repo = await _load(container, layers)
    assert await repo.estimate(lat, lon) == (True, None)  # nothing valid within reach: covered, no estimate


async def test_service_reads_the_local_tiles_and_leaves_uncovered_places_for_later(container):
    service = container.application.soil_context_service()
    repo = await _load(container, _layers({"phh2o": 66, "soc": 120, "nitrogen": 110, "cec": 150}))
    with patch.object(service, "soilgrids", repo):
        inside = await service.add_soilgrids(None, 20.5, -100.5)
        assert inside["soilgrids"]["depths"]["0-5cm"]["ph"] == 6.6 and inside["soilgrids"]["resolution_m"] == 1000
        assert await service.add_soilgrids(None, 40.0, -3.0) is None  # Spain: no loaded grid, nothing is invented
        # creating a field reads the tiles right away (a local query)
        context = await service.lookup(20.5, -100.5)
        assert context.soilgrids.depths["0-5cm"].ph == 6.6 and context.soilgrids_checked is True
