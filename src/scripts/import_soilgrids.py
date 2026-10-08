"""
One-off ETL: loads the SoilGrids GeoTIFFs (1 km, one folder per region) into the database as georeferenced tiles,
so a field's pH / organic carbon / nitrogen / CEC come from our own database (see
src/application/soil_data/grid_models.py), not from a public service.

Expected layout (what the download produced), one file per property and depth:

    <dir>/mexico/phh2o_0-5cm_mean.tif   <dir>/mexico/soc_5-15cm_mean.tif ...
    <dir>/argentina/...

    uv run python -m src.scripts.import_soilgrids --dir raw_data/downloads/soilgrids \\
        [--depths 0-5cm,5-15cm,15-30cm] [--regions mexico,argentina]

Only the topsoil depths are loaded by default (0-30 cm: what a garden or a crop feels). Every region folder becomes one
grid; running it again replaces that grid. After it finishes the TIFFs are no longer needed at runtime.
Fields already created get their SoilGrids data the first time an analysis or the soil tool asks (ensure_soilgrids).
"""
import argparse
import asyncio
import logging
from pathlib import Path

import numpy as np
import tifffile

from src.application.soil_data.grid_models import SoilGridsGrid, SoilGridsTile
from src.application.soil_data.soilgrids_repository import (
    DEPTHS,
    NODATA,
    PROPERTIES,
    TILE_SIZE,
    SoilGridsRepository,
    encode_tile,
)
from src.config.bootstrap import build_container
from src.shared.database import dispose_database_connections

logger = logging.getLogger("src.scripts.import_soilgrids")


def read_layer(path: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """(pixels, (west, north, res_lon, res_lat)) of a north-up GeoTIFF."""
    with tifffile.TiffFile(path) as tif:
        page = tif.pages[0]
        res_lon, res_lat, _ = page.tags["ModelPixelScaleTag"].value
        _, _, _, west, north, _ = page.tags["ModelTiepointTag"].value
        return page.asarray().astype("<i2"), (west, north, res_lon, res_lat)


def tiles_of(array: np.ndarray, size: int = TILE_SIZE):
    """(tx, ty, block) for every size x size block that holds at least one valid pixel; edges padded with no-data."""
    height, width = array.shape
    padded = np.full((-(-height // size) * size, -(-width // size) * size), NODATA, dtype="<i2")
    padded[:height, :width] = array
    for ty in range(padded.shape[0] // size):
        for tx in range(padded.shape[1] // size):
            block = padded[ty * size:(ty + 1) * size, tx * size:(tx + 1) * size]
            if (block != NODATA).any():
                yield tx, ty, block


def build_grid(region_dir: Path, depths: tuple[str, ...]) -> tuple[SoilGridsGrid, list[SoilGridsTile]]:
    tiles: list[SoilGridsTile] = []
    grid = None
    for prop in PROPERTIES:
        for depth in depths:
            path = region_dir / f"{prop}_{depth}_mean.tif"
            if not path.is_file():
                raise SystemExit(f"Missing {path}")
            array, (west, north, res_lon, res_lat) = read_layer(path)
            if grid is None:
                grid = SoilGridsGrid(
                    grid=region_dir.name, min_lon=west, max_lat=north, res_lon=res_lon, res_lat=res_lat,
                    width=array.shape[1], height=array.shape[0], tile_size=TILE_SIZE, resolution_m=1000,
                )
            elif array.shape != (grid.height, grid.width):
                raise SystemExit(f"{path} has a different shape than the other layers of {region_dir.name}")
            tiles += [
                SoilGridsTile(grid=region_dir.name, prop=prop, depth=depth, tx=tx, ty=ty, data=encode_tile(block))
                for tx, ty, block in tiles_of(array)
            ]
    return grid, tiles


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.scripts.import_soilgrids")
    parser.add_argument("--dir", type=Path, required=True, help="Folder with one subfolder per region")
    parser.add_argument("--regions", help="Comma-separated subfolders to load (default: all)")
    parser.add_argument("--depths", default=",".join(DEPTHS), help="Comma-separated depth labels")
    args = parser.parse_args()
    depths = tuple(d.strip() for d in args.depths.split(",") if d.strip())
    wanted = {r.strip() for r in args.regions.split(",")} if args.regions else None
    regions = sorted(p for p in args.dir.iterdir() if p.is_dir() and (wanted is None or p.name in wanted))
    if not regions:
        raise SystemExit(f"No region folders under {args.dir}")

    container = build_container()
    repo = SoilGridsRepository(container.db_session_factory())
    try:
        for region in regions:
            logger.info(f"Reading {region.name} ...")
            grid, tiles = await asyncio.to_thread(build_grid, region, depths)
            await repo.replace_grid(grid, tiles)
            kb = sum(len(t.data) for t in tiles) / 1024
            logger.info(
                f"{region.name}: {grid.width}x{grid.height} px at ({grid.min_lon:.3f}, {grid.max_lat:.3f}), "
                f"{len(tiles)} tiles, {kb / 1024:.1f} MB"
            )
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
