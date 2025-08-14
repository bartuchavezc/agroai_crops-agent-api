from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

logger = logging.getLogger(__name__)

class TimescaleMigration:
    """Migration manager for TimescaleDB specific configurations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def is_timescaledb_available(self) -> bool:
        """Check if TimescaleDB extension is available and enabled."""
        try:
            result = await self.session.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
            )
            return result.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking TimescaleDB availability: {e}")
            return False
    
    async def create_hypertable(self):
        """Creates TimescaleDB hypertable for weather_timeseries with proper structure."""
        try:
            # Check if hypertable already exists
            check_query = text("""
                SELECT 1 FROM timescaledb_information.hypertables 
                WHERE hypertable_name = 'weather_timeseries'
            """)
            result = await self.session.execute(check_query)
            if result.fetchone():
                logger.info("Hypertable 'weather_timeseries' already exists")
                return True
            
            # Check if table exists and has problematic unique constraints
            check_unique_constraint = text("""
                SELECT 1 FROM pg_constraint 
                WHERE conname = 'weather_timeseries_id_key' 
                AND contype = 'u'
            """)
            result = await self.session.execute(check_unique_constraint)
            
            if result.fetchone():
                logger.info("Dropping existing weather_timeseries table with conflicting constraints")
                await self.session.execute(text("DROP TABLE IF EXISTS weather_timeseries CASCADE"))
                await self.session.commit()
            
            # First create the table with SQL
            logger.info("Creating TimescaleDB-optimized table 'weather_timeseries'")
            
            create_table_sql = text("""
                CREATE TABLE IF NOT EXISTS weather_timeseries (
                    timestamp TIMESTAMP NOT NULL,
                    latitude FLOAT NOT NULL,
                    longitude FLOAT NOT NULL,
                    id INTEGER NOT NULL,
                    temperature FLOAT NOT NULL,
                    humidity FLOAT NOT NULL,
                    precipitation FLOAT NOT NULL,
                    wind_speed FLOAT NOT NULL,
                    wind_direction FLOAT NOT NULL,
                    pressure FLOAT NOT NULL,
                    soil_moisture FLOAT,
                    PRIMARY KEY (timestamp, latitude, longitude)
                )
            """)
            
            await self.session.execute(create_table_sql)
            
            # Create indexes
            indexes_sql = [
                text("CREATE INDEX IF NOT EXISTS ts_idx_time ON weather_timeseries (timestamp)"),
                text("CREATE INDEX IF NOT EXISTS ts_idx_location ON weather_timeseries (latitude, longitude)"),
                text("CREATE INDEX IF NOT EXISTS ts_idx_time_location ON weather_timeseries (timestamp, latitude, longitude)"),
                text("CREATE INDEX IF NOT EXISTS ts_idx_id ON weather_timeseries (id)")
            ]
            
            for index_sql in indexes_sql:
                await self.session.execute(index_sql)
            
            # Create sequence for ID generation
            sequence_sql = text("CREATE SEQUENCE IF NOT EXISTS weather_timeseries_id_seq")
            await self.session.execute(sequence_sql)
            
            await self.session.commit()
            logger.info("✅ Created weather_timeseries table with composite primary key")
            
            # Now create the hypertable (this should work with proper primary key)
            logger.info("Converting weather_timeseries to TimescaleDB hypertable")
            hypertable_query = text("""
                SELECT create_hypertable(
                    'weather_timeseries', 
                    'timestamp',
                    chunk_time_interval => INTERVAL '1 day',
                    if_not_exists => TRUE
                )
            """)
            await self.session.execute(hypertable_query)
            await self.session.commit()
            logger.info("✅ Successfully created TimescaleDB hypertable 'weather_timeseries'")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error creating TimescaleDB hypertable: {e}")
            # Don't raise here to prevent app startup failure
            return False
    
    async def create_retention_policy(self, retention_days: int = 1825):
        """Creates data retention policy for TimescaleDB."""
        try:
            # Check if retention policy already exists
            check_policy = text("""
                SELECT 1 FROM timescaledb_information.jobs 
                WHERE proc_name = 'policy_retention' 
                AND hypertable_name = 'weather_timeseries'
            """)
            result = await self.session.execute(check_policy)
            if result.fetchone():
                logger.info("Retention policy for 'weather_timeseries' already exists")
                return True
            
            # Create retention policy
            retention_query = text(f"""
                SELECT add_retention_policy(
                    'weather_timeseries', 
                    INTERVAL '{retention_days} days'
                )
            """)
            await self.session.execute(retention_query)
            await self.session.commit()
            logger.info(f"Created retention policy for {retention_days} days")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error creating retention policy: {e}")
            # Don't raise here as retention policy is optional
            return False
    
    async def create_compression_policy(self):
        """Creates compression policy for TimescaleDB to optimize storage."""
        try:
            # Check if compression policy already exists
            check_compression = text("""
                SELECT 1 FROM timescaledb_information.jobs 
                WHERE proc_name = 'policy_compression' 
                AND hypertable_name = 'weather_timeseries'
            """)
            result = await self.session.execute(check_compression)
            if result.fetchone():
                logger.info("Compression policy for 'weather_timeseries' already exists")
                return True
            
            # Enable compression on table
            compression_query = text("""
                ALTER TABLE weather_timeseries SET (
                    timescaledb.compress,
                    timescaledb.compress_segmentby = 'latitude, longitude'
                )
            """)
            await self.session.execute(compression_query)
            
            # Add compression policy (compress chunks older than 7 days)
            policy_query = text("""
                SELECT add_compression_policy(
                    'weather_timeseries', 
                    INTERVAL '7 days'
                )
            """)
            await self.session.execute(policy_query)
            await self.session.commit()
            logger.info("Created compression policy for chunks older than 7 days")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error creating compression policy: {e}")
            # Don't raise here as compression is optional
            return False
    
    async def run_all_migrations(self, retention_days: int = 1825):
        """Runs all TimescaleDB migrations."""
        logger.info("Starting TimescaleDB migrations for weather_timeseries")
        
        if not await self.is_timescaledb_available():
            logger.warning("TimescaleDB extension not available, skipping TimescaleDB migrations")
            return False
        
        success = True
        
        # Core hypertable creation is required
        try:
            await self.create_hypertable()
        except Exception as e:
            logger.error(f"Failed to create hypertable: {e}")
            success = False
            
        # Optional optimizations
        if success:
            await self.create_retention_policy(retention_days)
            await self.create_compression_policy()
        
        if success:
            logger.info("TimescaleDB migrations completed successfully")
        else:
            logger.error("TimescaleDB migrations completed with errors")
            
        return success 