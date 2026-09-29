"""
One-off ETL: loads the two INTA soil reference datasets into Postgres (PostGIS) and backfills the
`soil_context` cache on every existing field that already has coordinates.

Never run as part of the app's normal startup — this is a manual, one-time import, run once per
environment (local + production) against the raw source files:
  - "Suelos de la República Argentina" 1:500.000 (shapefile: .shp + .shx + .dbf, same basename)
  - National pH (0-30cm) raster (GeoTIFF)

    uv run python -m src.scripts.import_soil_data \
        --shp /path/to/suelos_argentina_1_500.shp \
        --tif /path/to/pH_0_30_nuevo_recorte_M.tif

After it finishes, the source files are no longer needed anywhere — everything queried at runtime lives
in soil_map_units/soil_ph_points (see src/application/soil_data/), and it's safe to delete them.

Re-running is safe: both tables are truncated and reloaded from scratch each time.
"""
import argparse
import asyncio
import logging

import numpy as np
import shapefile
import tifffile
from sqlalchemy import text

from src.config.bootstrap import build_container
from src.shared.database import dispose_database_connections

logger = logging.getLogger("src.scripts.import_soil_data")

# Sentinel Copernicus/GDAL float32 nodata convention for this raster, plus a second, undocumented
# "no reliable data" flag found in the source file itself: ~6% of otherwise-valid pixels carry the
# literal value 100, which isn't a real pH reading (pH tops out around 14) — both are treated as absent.
_PH_NODATA = -3.4028234663852886e38
_PH_MAX_PLAUSIBLE = 14.0

_MAP_UNIT_COLUMNS = (
    "id", "provincia", "unit_symbol", "unit_type", "productivity_index", "dominant_percent", "position",
    "soil_order", "great_group", "subgroup", "texture_surface", "texture_subsoil", "drainage",
    "depth_cm", "alkalinity", "erosion_hydric", "erosion_eolic", "rockiness", "floodability",
)


def _signed_area(ring: list[tuple[float, float]]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _shape_to_wkt(shp) -> str | None:
    """Shapefile Polygon rings: clockwise = outer shell, counter-clockwise = hole (ESRI convention).
    Groups the shapefile's flat list of rings into proper MULTIPOLYGON components (with holes)."""
    points = shp.points
    if not points:
        return None
    parts = list(shp.parts) + [len(points)]
    rings = [points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
    polygons: list[list[list[tuple[float, float]]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        if _signed_area(ring) < 0 or not polygons:
            polygons.append([ring])
        else:
            polygons[-1].append(ring)
    if not polygons:
        return None

    def ring_wkt(ring: list[tuple[float, float]]) -> str:
        return "(" + ",".join(f"{x} {y}" for x, y in ring) + ")"

    poly_wkt = ",".join("(" + ",".join(ring_wkt(r) for r in poly) + ")" for poly in polygons)
    return f"MULTIPOLYGON({poly_wkt})"


def _clean_str(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _clean_num(value) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


async def _import_map_units(session_factory, shp_path: str) -> int:
    logger.info(f"Reading shapefile {shp_path} ...")
    sf = shapefile.Reader(shp_path, encoding="latin-1", encodingErrors="replace")
    rows = []
    for sr in sf.iterShapeRecords():
        wkt = _shape_to_wkt(sr.shape)
        if wkt is None:
            continue
        rec = sr.record.as_dict()
        rows.append({
            "id": int(rec["ogc_fid"]),
            "provincia": _clean_str(rec.get("provincia")),
            "unit_symbol": _clean_str(rec.get("simbc")),
            "unit_type": _clean_str(rec.get("tipo_uc")),
            "productivity_index": _clean_num(rec.get("ind_prod")),
            "dominant_percent": _clean_num(rec.get("porc_sue1")),
            "position": _clean_str(rec.get("posi_sue1")),
            "soil_order": _clean_str(rec.get("orden_sue1")),
            "great_group": _clean_str(rec.get("ggrup_sue1")),
            "subgroup": _clean_str(rec.get("sgrup_sue1")),
            "texture_surface": _clean_str(rec.get("text_sups1")),
            "texture_subsoil": _clean_str(rec.get("text_bs1")),
            "drainage": _clean_str(rec.get("drenaje_s1")),
            "depth_cm": _clean_num(rec.get("profund_s1")),
            "alkalinity": _clean_str(rec.get("alcalin_s1")),
            "erosion_hydric": _clean_str(rec.get("erhidr_s1")),
            "erosion_eolic": _clean_str(rec.get("ereoli_s1")),
            "rockiness": _clean_str(rec.get("rocos_s1")),
            "floodability": _clean_str(rec.get("anegab_s1")),
            "wkt": wkt,
        })
    logger.info(f"Parsed {len(rows)} soil map unit polygons; loading into Postgres ...")

    columns = [c for c in _MAP_UNIT_COLUMNS]
    placeholders = ", ".join(f":{c}" for c in columns)
    insert_sql = text(
        f"INSERT INTO soil_map_units ({', '.join(columns)}, geom) "
        f"VALUES ({placeholders}, ST_GeomFromText(:wkt, 4326))"
    )
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE soil_map_units"))
        batch_size = 500
        for i in range(0, len(rows), batch_size):
            await session.execute(insert_sql, rows[i:i + batch_size])
        await session.commit()
    return len(rows)


async def _import_ph_raster(session_factory, tif_path: str, stride: int) -> int:
    logger.info(f"Reading raster {tif_path} (stride={stride}) ...")
    tif = tifffile.TiffFile(tif_path)
    page = tif.pages[0]
    arr = page.asarray()
    sx, sy, _ = page.tags["ModelPixelScaleTag"].value
    i0, j0, _, x0, y0, _ = page.tags["ModelTiepointTag"].value

    rows_idx, cols_idx = np.where(
        (arr != _PH_NODATA) & (arr <= _PH_MAX_PLAUSIBLE) & np.isfinite(arr)
    )
    # Downsample: this is a coarse (~1km) interpolated national surface, not survey-precision data, so a
    # denser grid than a few km buys nothing for a handful of garden-scale field lookups but costs a lot
    # of rows.
    keep = (rows_idx % stride == 0) & (cols_idx % stride == 0)
    rows_idx, cols_idx = rows_idx[keep], cols_idx[keep]
    values = arr[rows_idx, cols_idx]
    lons = x0 + (cols_idx + 0.5) * sx
    lats = y0 - (rows_idx + 0.5) * sy
    logger.info(f"{len(values)} valid pH samples after filtering nodata/implausible/downsampling ...")

    insert_sql = text(
        "INSERT INTO soil_ph_points (ph, geom) VALUES (:ph, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
    )
    async with session_factory() as session:
        await session.execute(text("TRUNCATE TABLE soil_ph_points"))
        batch_size = 5000
        total = len(values)
        for i in range(0, total, batch_size):
            batch = [
                {"ph": float(values[j]), "lon": float(lons[j]), "lat": float(lats[j])}
                for j in range(i, min(i + batch_size, total))
            ]
            await session.execute(insert_sql, batch)
            if i % (batch_size * 20) == 0:
                logger.info(f"  ... {i}/{total}")
        await session.commit()
    return total


async def _backfill_fields(container) -> int:
    logger.info("Backfilling soil_context on existing fields with coordinates ...")
    farm_repo = container.application.farm_repository()
    soil_service = container.application.soil_context_service()
    fields = await farm_repo.list_all_fields_with_coordinates()
    updated = 0
    for field in fields:
        context = await soil_service.lookup(field.latitude, field.longitude)
        payload = context.model_dump(mode="json") if context else None
        await farm_repo.update_field(field.account_id, field.id, {"soil_context": payload})
        updated += 1
    logger.info(f"Backfilled {updated} field(s).")
    return updated


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.scripts.import_soil_data")
    parser.add_argument("--shp", required=True, help="Path to the .shp file (siblings .shx/.dbf expected)")
    parser.add_argument("--tif", required=True, help="Path to the pH GeoTIFF")
    parser.add_argument("--ph-stride", type=int, default=4, help="Keep 1 of every N pixels per axis (default 4)")
    args = parser.parse_args()

    container = build_container()
    session_factory = container.db_session_factory()
    try:
        n_units = await _import_map_units(session_factory, args.shp)
        n_points = await _import_ph_raster(session_factory, args.tif, args.ph_stride)
        n_backfilled = await _backfill_fields(container)
        logger.info(
            f"Done: {n_units} soil map units, {n_points} pH points, {n_backfilled} fields backfilled."
        )
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
