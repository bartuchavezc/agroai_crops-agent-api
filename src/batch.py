"""
Batch jobs.

    python -m src.batch smn                  # SMN forecast ETL for every field + proactive alerts, once
    python -m src.batch smn --every-hours 6  # same, forever (used by the `worker` compose service)
    python -m src.batch smn --force          # reload even if the latest cycle is already loaded
    python -m src.batch reminders                     # notify the reminders that are due, once
    python -m src.batch reminders --every-minutes 10  # same, forever (the `reminders` compose service)
    python -m src.batch satellite                     # sync every field's satellite series + alerts, once
    python -m src.batch satellite --every-hours 24    # same, forever (the `satellite` compose service)
    python -m src.batch satellite-backfill --years 5 [--field-id ID] [--source sentinel2|sentinel1]
"""
import argparse
import asyncio
import logging
import time
from typing import Optional

from src.application.satellite.ingest import KIND_BATCH, BudgetExceeded
from src.config.bootstrap import build_container
from src.shared.database import dispose_database_connections
from src.shared.utils import get_logger

logger = get_logger("src.batch")


async def run_smn(container, force: bool = False) -> None:
    fields = await container.application.farm_repository().list_all_fields_with_coordinates()
    points = [(f.latitude, f.longitude) for f in fields]
    etl_result = await container.data_providers.smn_etl().run(points, force=force)
    logger.info(f"SMN ETL: {etl_result}")
    alerts_result = await container.application.forecast_alert_service().run()
    logger.info(f"Forecast alerts: {alerts_result}")

    irrigation_result = await container.application.irrigation_service().run_proactive_alerts()
    logger.info(f"Irrigation alerts: {irrigation_result}")

    # Copernicus has its own job (`satellite`, below): it runs on its own cadence and processing-unit
    # budget, so a slow or capped Copernicus never delays the forecast alerts.


async def run_satellite(container, years: Optional[int] = None, field_id: Optional[str] = None,
                        sources: Optional[list[str]] = None, force: bool = False) -> None:
    """Keep every field's series complete and fresh (backfill missing history, then the new passes), then
    raise the series-based alerts. With `years` (the backfill) it also fetches the pixels of every pass in the
    series that has none yet; the daily run keeps the last days. Stops spending once the month's batch budget
    is used up (alerts still run on the stored data). Disabled unless SATELLITE_INGEST_ENABLED=true or `force`
    (the explicit backfill command)."""
    app = container.application
    if not force and not container.config.satellite.ingest_enabled():
        logger.info("Satellite ingest disabled (SATELLITE_INGEST_ENABLED=false); nothing to do")
        return
    fields = await app.farm_repository().list_all_fields_with_coordinates()
    if field_id:
        fields = [f for f in fields if str(f.id) == field_id]
    ingest = app.satellite_ingest_service()
    satellite = app.satellite_service()
    budget_hit = False
    totals = {"fields": len(fields), "synced": 0, "observations": 0, "processing_units": 0.0, "alert_matches": 0}
    for field in fields:
        if not budget_hit:
            try:
                report = await ingest.sync_field(
                    field, kind=KIND_BATCH, history_years=years, sources=sources, chips="all" if years else "recent"
                )
                totals["synced"] += 1
                totals["observations"] += report.observations
                totals["processing_units"] += report.processing_units
                logger.info(f"Satellite sync {field.id}: {report.to_dict()}")
            except BudgetExceeded as e:
                budget_hit = True
                logger.warning(f"{e}; remaining fields keep their stored series this run")
            except Exception:
                logger.exception(f"Satellite sync failed for field {field.id}")
        try:
            totals["alert_matches"] += await satellite.run_alerts_for_field(field)
        except Exception:
            logger.exception(f"Satellite alerts failed for field {field.id}")
    logger.info(f"Satellite batch: {totals}; usage this month: {await ingest.usage()}")


async def run_reminders(container) -> None:
    result = await container.application.planning_service().run_due_reminders()
    if result["notified"]:
        logger.info(f"Reminders: {result}")


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.batch")
    sub = parser.add_subparsers(dest="job", required=True)
    smn = sub.add_parser("smn", help="SMN forecast ETL + proactive forecast alerts")
    smn.add_argument("--force", action="store_true")
    smn.add_argument("--every-hours", type=float, default=None)
    reminders = sub.add_parser("reminders", help="In-app notifications for the reminders that are due")
    reminders.add_argument("--every-minutes", type=float, default=None)
    satellite = sub.add_parser("satellite", help="Copernicus series sync (backfill + new passes) + satellite alerts")
    satellite.add_argument("--every-hours", type=float, default=None)
    backfill = sub.add_parser("satellite-backfill", help="Extend the satellite series history, once")
    backfill.add_argument("--years", type=int, required=True)
    backfill.add_argument("--field-id", default=None)
    backfill.add_argument("--source", choices=["sentinel2", "sentinel1"], default=None)
    args = parser.parse_args()

    if args.job == "reminders":
        job, name = run_reminders, "Reminders"
        interval = args.every_minutes * 60 if args.every_minutes else None
    elif args.job == "satellite":
        job, name = run_satellite, "Satellite"
        interval = args.every_hours * 3600 if args.every_hours else None
    elif args.job == "satellite-backfill":
        sources = [args.source] if args.source else None
        job = lambda c: run_satellite(c, years=args.years, field_id=args.field_id, sources=sources, force=True)  # noqa: E731
        name, interval = "Satellite backfill", None
    else:
        job, name = (lambda c: run_smn(c, force=args.force)), "SMN"
        interval = args.every_hours * 3600 if args.every_hours else None

    container = build_container()
    try:
        while True:
            started = time.monotonic()
            try:
                await job(container)
            except Exception:
                logger.exception(f"{name} batch failed")
                if interval is None:
                    raise
            if interval is None:
                break
            await asyncio.sleep(max(30.0, interval - (time.monotonic() - started)))
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.getLogger("botocore").setLevel(logging.WARNING)
    asyncio.run(main())
