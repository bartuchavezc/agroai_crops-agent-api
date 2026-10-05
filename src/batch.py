"""
Batch jobs.

    python -m src.batch smn                  # SMN forecast ETL for every field + proactive alerts, once
    python -m src.batch smn --every-hours 6  # same, forever (used by the `worker` compose service)
    python -m src.batch smn --force          # reload even if the latest cycle is already loaded
    python -m src.batch reminders                     # notify the reminders that are due, once
    python -m src.batch reminders --every-minutes 10  # same, forever (the `reminders` compose service)
"""
import argparse
import asyncio
import logging
import time

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

    # No automatic Copernicus calls here on purpose: satellite checks only happen when the user
    # explicitly asks (chat) or explicitly hits "Regenerar imagen"/opens the field page — never on a
    # schedule or as a side effect of something else, however well-intentioned ("check after a storm").


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
    args = parser.parse_args()

    if args.job == "reminders":
        job, name = run_reminders, "Reminders"
        interval = args.every_minutes * 60 if args.every_minutes else None
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
