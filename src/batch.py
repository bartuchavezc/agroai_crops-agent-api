"""
Batch jobs.

    python -m src.batch smn                  # SMN forecast ETL for every field + proactive alerts, once
    python -m src.batch smn --every-hours 6  # same, forever (used by the `worker` compose service)
    python -m src.batch smn --force          # reload even if the latest cycle is already loaded
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


async def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.batch")
    sub = parser.add_subparsers(dest="job", required=True)
    smn = sub.add_parser("smn", help="SMN forecast ETL + proactive forecast alerts")
    smn.add_argument("--force", action="store_true")
    smn.add_argument("--every-hours", type=float, default=None)
    args = parser.parse_args()

    container = build_container()
    try:
        while True:
            started = time.monotonic()
            try:
                await run_smn(container, force=args.force)
            except Exception:
                logger.exception("SMN batch failed")
                if args.every_hours is None:
                    raise
            if args.every_hours is None:
                break
            await asyncio.sleep(max(60.0, args.every_hours * 3600 - (time.monotonic() - started)))
    finally:
        await dispose_database_connections()


if __name__ == "__main__":
    logging.getLogger("botocore").setLevel(logging.WARNING)
    asyncio.run(main())
