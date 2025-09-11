#!/usr/bin/env python3
"""
Database and TimescaleDB Migration Script

This script can be run as a Kubernetes job to initialize:
1. PostgreSQL database tables
2. TimescaleDB extensions and hypertables
3. Weather data tables and policies

Usage:
    python migrations.py [--config CONFIG_FILE] [--dry-run] [--verbose]
"""

import asyncio
import argparse
import logging
import sys
import os
from pathlib import Path
from typing import Optional

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.app.config.core import load_app_config
from src.app.database import init_database_connections, init_db_tables
from src.app.timeseries import init_timescale_connections, init_timescale_tables
from src.app.utils.logger import get_logger

# Import all models so they register with shared_metadata
# Farm Management models
from src.app.farm_management.domain.account_model import *
from src.app.farm_management.domain.field_model import *
from src.app.farm_management.domain.crop_cycle_model import *
from src.app.farm_management.domain.crop_master_model import *
from src.app.farm_management.domain.report_campaign_model import *

# Reports models
from src.app.reports.domain.report_model import *

# Users models
from src.app.users.domain.user_model import *

# Weather data models
from src.app.weather_data.infrastructure.entities.weather_measurements import *
from src.app.weather_data.infrastructure.entities.timescale_weather_series import *

# Weather zones models
from src.app.weather_zones.infrastructure.models.weather_zone import *

logger = get_logger(__name__)

class MigrationRunner:
    """Handles database and TimescaleDB migrations."""
    
    def __init__(self, config: dict, dry_run: bool = False, verbose: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.verbose = verbose
        
        # Set up logging
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        logger.info(f"Migration runner initialized (dry_run={dry_run})")
    
    async def run_migrations(self) -> bool:
        """Run all database migrations."""
        try:
            logger.info("🚀 Starting database migrations...")
            
            # Step 1: Initialize database connections
            await self._init_connections()
            
            # Step 2: Run PostgreSQL migrations
            await self._run_postgres_migrations()
            
            # Step 3: Run TimescaleDB migrations
            await self._run_timescale_migrations()
            
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
    
    async def _run_postgres_migrations(self):
        """Run PostgreSQL table migrations."""
        logger.info("🗄️  Running PostgreSQL migrations...")
        
        if self.dry_run:
            logger.info("🔍 DRY RUN: Would create PostgreSQL tables")
            return
        
        # Debug: Check what tables are in metadata before creating
        from src.app.database import shared_metadata
        logger.info(f"🔍 Tables in metadata before create_all: {len(shared_metadata.tables)}")
        logger.info(f"🔍 Table names: {list(shared_metadata.tables.keys())}")
        
        await init_db_tables()
        logger.info("✅ PostgreSQL tables created")
    
    async def _run_timescale_migrations(self):
        """Run TimescaleDB migrations."""
        logger.info("⏰ Running TimescaleDB migrations...")
        
        if self.dry_run:
            logger.info("🔍 DRY RUN: Would create TimescaleDB hypertables and policies")
            return
        
        await init_timescale_tables()
        logger.info("✅ TimescaleDB migrations completed")

def load_config(config_file: Optional[str] = None) -> dict:
    """Load application configuration."""
    if config_file and os.path.exists(config_file):
        logger.info(f"Loading config from: {config_file}")
        # You could implement custom config loading here
        # For now, we'll use the default config loader
        return load_app_config()
    else:
        logger.info("Loading default configuration")
        return load_app_config()

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run database and TimescaleDB migrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python migrations.py                    # Run migrations with default config
  python migrations.py --dry-run         # Show what would be done
  python migrations.py --verbose         # Show detailed output
  python migrations.py --config config.yaml  # Use custom config file
        """
    )
    
    parser.add_argument(
        "--config", "-c",
        help="Path to configuration file (optional)"
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
        config = load_config(args.config)
        
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
