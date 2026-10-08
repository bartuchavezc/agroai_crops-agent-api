"""
Measure what the satellite series really costs in Copernicus processing units, on a real field, before
turning the scheduled ingest on (SATELLITE_INGEST_ENABLED) or promising how many fields fit the free tier.

    uv run python -m src.scripts.copernicus_measure --field-id <uuid>          # a field from the DB
    uv run python -m src.scripts.copernicus_measure --lat -34.6 --lon -58.4     # ~500m box, no DB needed
    uv run python -m src.scripts.copernicus_measure --field-id <uuid> --compare-p5d --raw

It spends real units (a few requests over one year of data) and stores nothing in the series; when run
with --field-id the units are added to copernicus_usage (kind "batch") so the monthly budget stays honest.
Prints, per request: units spent, passes returned, mean cloud-free fraction; then an extrapolation:
units to backfill one field, units per month to keep it fresh (a daily sync re-reads ~18 days), and how
many fields fit in the batch budget. With --raw, also dumps the first interval's stats as returned by the
API (to check fields like geometryPixelCount against what the parser expects).
"""
import argparse
import asyncio
import json
import logging
import math
from datetime import date, timedelta
from typing import Optional

from src.application.satellite.ingest import INCREMENTAL_OVERLAP_DAYS, KIND_BATCH
from src.config.bootstrap import build_container
from src.providers.satellite.copernicus import SeriesResult
from src.shared.database import dispose_database_connections


def _row(label: str, result: Optional[SeriesResult]) -> dict:
    if result is None:
        print(f"  {label:<38} FAILED (see log)")
        return {"units": None, "passes": 0}
    fractions = [o.valid_fraction for o in result.observations if o.valid_fraction is not None]
    clear = f"{sum(fractions) / len(fractions):.2f}" if fractions else "-"
    units = "n/a" if result.processing_units is None else f"{result.processing_units:.4f}"
    print(
        f"  {label:<38} units={units:<10} requests={result.requests:<3}"
        f" passes={len(result.observations):<4} mean_clear={clear}"
    )
    return {"units": result.processing_units, "passes": len(result.observations)}


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.scripts.copernicus_measure")
    parser.add_argument("--field-id")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--compare-p5d", action="store_true", help="also measure a P5D aggregation for comparison")
    parser.add_argument("--no-s1", action="store_true")
    parser.add_argument("--raw", action="store_true", help="dump the first S2 interval as returned by the API")
    args = parser.parse_args()
    if not args.field_id and (args.lat is None or args.lon is None):
        parser.error("pass --field-id, or --lat and --lon")

    container = build_container()
    try:
        copernicus = container.data_providers.copernicus()
        if not copernicus.configured:
            raise SystemExit("COPERNICUS_CLIENT_ID/COPERNICUS_CLIENT_SECRET are not set.")
        config = container.config.satellite
        polygon = None
        lat, lon = args.lat, args.lon
        series_repo = None
        if args.field_id:
            fields = await container.application.farm_repository().list_all_fields_with_coordinates()
            field = next((f for f in fields if str(f.id) == args.field_id), None)
            if field is None:
                raise SystemExit(f"No field {args.field_id} with coordinates.")
            lat, lon, polygon = field.latitude, field.longitude, field.boundary
            series_repo = container.application.satellite_series_repository()
            print(f"Field '{field.name}' ({'drawn boundary' if polygon else '~500m box, no boundary drawn'})")

        today = date.today()
        year_ago = today - timedelta(days=365)
        incremental_from = today - timedelta(days=INCREMENTAL_OVERLAP_DAYS + 3)
        orbit = config.s1_orbit_direction()
        results: dict[str, dict] = {}
        spent = 0.0

        print("Sentinel-2 L2A (5 indices, P1D):")
        s2_year = await copernicus.s2_series(lat, lon, year_ago, today, polygon=polygon)
        results["s2_year"] = _row("1 year", s2_year)
        s2_inc = await copernicus.s2_series(lat, lon, incremental_from, today, polygon=polygon)
        results["s2_incremental"] = _row(f"incremental ({INCREMENTAL_OVERLAP_DAYS + 3} days)", s2_inc)
        if args.compare_p5d:
            s2_p5d = await copernicus.s2_series(lat, lon, year_ago, today, polygon=polygon, aggregation_interval="P5D")
            results["s2_year_p5d"] = _row("1 year, P5D (comparison only)", s2_p5d)
        if not args.no_s1:
            print(f"Sentinel-1 GRD ({orbit}, P1D):")
            s1_year = await copernicus.s1_series(lat, lon, year_ago, today, polygon=polygon, orbit_direction=orbit)
            results["s1_year"] = _row("1 year", s1_year)
            s1_inc = await copernicus.s1_series(
                lat, lon, incremental_from, today, polygon=polygon, orbit_direction=orbit
            )
            results["s1_incremental"] = _row(f"incremental ({INCREMENTAL_OVERLAP_DAYS + 3} days)", s1_inc)

        for r in results.values():
            spent += r["units"] or 0.0
        if series_repo is not None:
            await series_repo.add_usage(KIND_BATCH, spent, requests=len(results))

        if args.raw:
            # Same request the parser sees, printed as-is: checks the stats keys (sampleCount, noDataCount,
            # geometryPixelCount, percentiles) against what CopernicusAdapter._pixels/_parse_s2 expect.
            captured: list = []
            original = copernicus._statistics

            async def capture(body):
                payload, spent_units = await original(body)
                captured.append(payload)
                return payload, spent_units

            copernicus._statistics = capture
            await copernicus.s2_series(lat, lon, today - timedelta(days=10), today, polygon=polygon)
            copernicus._statistics = original
            first = next((i for p in captured if p for i in p.get("data", [])), None)
            print("\nRaw first S2 interval:", json.dumps(first, indent=1)[:3000] if first else "none")

        def units(key: str) -> Optional[float]:
            return (results.get(key) or {}).get("units")

        year_units = (units("s2_year") or 0.0) + (units("s1_year") or 0.0)
        inc_units = (units("s2_incremental") or 0.0) + (units("s1_incremental") or 0.0)
        years = int(config.backfill_years())
        budget = float(config.batch_pu_budget())
        backfill = year_units * years
        monthly = inc_units * 30
        print("\nExtrapolation (batch budget "
              f"{budget:.0f} units/month, {years}-year backfill, daily sync):")
        print(f"  backfill per field:           ~{backfill:.2f} units (one-off)")
        print(f"  keeping one field fresh:      ~{monthly:.2f} units/month")
        if monthly:
            print(f"  fields that fit (steady):     ~{math.floor(budget / monthly)}")
        if backfill:
            print(f"  new fields backfilled/month:  ~{math.floor(budget / backfill)} (if nothing else ran)")
        print(f"  units spent by this measurement: {spent:.2f}")
        if None in (units("s2_year"), units("s2_incremental")):
            print("  (the API didn't report x-processingunits-spent for some request; check the dashboard)")
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
