#!/usr/bin/env python3
"""
Database Migration Script for New 3-Layer Architecture

This script initializes the database tables for the new architecture:
- Auth layer: Users
- Action layer: Reports

Usage:
    python migrations_new.py [--dry-run] [--verbose]
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.config.settings import load_app_config
from src.shared.database.postgres import init_database_connections
from src.shared.database.timescale import init_timescale_connections
from src.shared.utils.logger import get_logger

# Import new architecture models
from src.auth.domain.models import Account, User, UserProfile
from src.action.reports.report_repository import ReportModel

logger = get_logger(__name__)


class MigrationRunner:
    """Handles database migrations for the new architecture."""

    def __init__(self, config: dict, dry_run: bool = False, verbose: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.verbose = verbose

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        logger.info(f"Migration runner initialized (dry_run={dry_run})")

    async def run_migrations(self) -> bool:
        """Run all database migrations."""
        try:
            logger.info("🚀 Starting database migrations for new architecture...")

            # Step 1: Initialize database connections
            await self._init_connections()

            # Step 2: Create tables
            await self._create_tables()

            logger.info("✅ All migrations completed successfully!")
            return True

        except Exception as e:
            logger.error(f"❌ Migration failed: {str(e)}")
            if self.verbose:
                logger.exception("Full traceback:")
            return False

    async def _init_connections(self):
        """Initialize database connections."""
        logger.info("📡 Initializing database connections...")

        # PostgreSQL connection
        db_config = self.config.get("database", {})
        db_url = db_config.get("url")
        db_echo = db_config.get("echo", False)

        if not db_url:
            raise ValueError("DATABASE_URL not found in configuration")

        logger.info(f"Connecting to PostgreSQL: {db_url.split('@')[1] if '@' in db_url else '***'}")
        init_database_connections(db_url=db_url, echo_sql=db_echo)

        # TimescaleDB connection
        ts_config = self.config.get("timescale", {})
        ts_url = ts_config.get("url")
        ts_echo = ts_config.get("echo", False)

        if not ts_url:
            raise ValueError("TIMESCALE_URL not found in configuration")

        logger.info(f"Connecting to TimescaleDB: {ts_url.split('@')[1] if '@' in ts_url else '***'}")
        init_timescale_connections(timescale_url=ts_url, echo_sql=ts_echo)

        logger.info("✅ Database connections initialized")

    async def _create_tables(self):
        """Create all database tables."""
        logger.info("🗄️  Creating database tables...")

        if self.dry_run:
            logger.info("🔍 DRY RUN: Would create tables")
            from src.shared.database import shared_metadata
            logger.info(f"🔍 Tables that would be created: {list(shared_metadata.tables.keys())}")
            return

        # Import the initialization functions
        from src.shared.database.postgres import init_db_tables
        from src.shared.database.timescale import init_timescale_tables

        # Create PostgreSQL tables
        await init_db_tables()

        # Create TimescaleDB tables (if any needed)
        await init_timescale_tables()

        logger.info("✅ Database tables created")


def load_config() -> dict:
    """Load application configuration."""
    logger.info("Loading default configuration")
    return load_app_config()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run database migrations for new architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrations_new.py                    # Run migrations
  python migrations_new.py --dry-run         # Show what would be done
  python migrations_new.py --verbose         # Show detailed output
        """
    )

    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="Show what would be done without making changes"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed logging output"
    )

    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_arguments()

    # Set up basic logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    try:
        # Load configuration
        config = load_config()

        # Create migration runner
        runner = MigrationRunner(
            config=config,
            dry_run=args.dry_run,
            verbose=args.verbose
        )

        # Run migrations
        success = await runner.run_migrations()

        if success:
            logger.info("🎉 Migration job completed successfully")
            sys.exit(0)
        else:
            logger.error("💥 Migration job failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("⏹️  Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Unexpected error: {str(e)}")
        if args.verbose:
            logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())