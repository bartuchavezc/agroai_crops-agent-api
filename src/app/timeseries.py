from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator, Optional
from sqlalchemy import text
from src.app.database import shared_metadata
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger(__name__)

# Globals for TimescaleDB connections
_timescale_engine: Optional[create_async_engine] = None
_TimescaleSessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

def init_timescale_connections(timescale_url: str, echo_sql: bool = False):
    """Initializes the TimescaleDB engine and session factory.
    This should be called once at application startup after config is loaded.
    """
    global _timescale_engine, _TimescaleSessionLocal
    if _timescale_engine is not None:
        return

    _timescale_engine = create_async_engine(timescale_url, echo=echo_sql)
    _TimescaleSessionLocal = async_sessionmaker(
        bind=_timescale_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    logger.info("TimescaleDB connections initialized")

async def check_timescaledb_extension() -> bool:
    """Check if TimescaleDB extension is available."""
    if not _timescale_engine:
        return False
    
    try:
        async with get_timescale_db_session() as session:
            result = await session.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"))
            return result.fetchone() is not None
    except Exception as e:
        logger.warning(f"Could not check TimescaleDB extension: {e}")
        return False

async def init_timescale_tables():
    """Creates TimescaleDB tables and hypertables if they don't exist.
    Requires init_timescale_connections to have been called.
    """
    if not _timescale_engine:
        raise RuntimeError("TimescaleDB engine not initialized. Call init_timescale_connections first.")
    
    # Create standard tables first
    async with _timescale_engine.begin() as conn:
        await conn.run_sync(shared_metadata.create_all)
        logger.info("TimescaleDB standard tables created successfully")
    
    # Run TimescaleDB specific migrations if extension is available
    if await check_timescaledb_extension():
        logger.info("TimescaleDB extension detected, running TimescaleDB migrations")
        await run_timescale_migrations()
    else:
        logger.warning("TimescaleDB extension not found, using regular PostgreSQL mode")

async def run_timescale_migrations():
    """Runs TimescaleDB specific migrations."""
    try:
        from src.app.weather_data.migrations.timescale_migration import TimescaleMigration
        
        async with get_timescale_db_session() as session:
            migration = TimescaleMigration(session)
            success = await migration.run_all_migrations()
            if success:
                logger.info("TimescaleDB migrations completed successfully")
            else:
                logger.warning("TimescaleDB migrations completed with some errors")
            
    except ImportError:
        logger.warning("TimescaleDB migration not available, skipping...")
    except Exception as e:
        logger.error(f"Error running TimescaleDB migrations: {e}")
        # Don't raise here to prevent app startup failure

async def get_timescale_session() -> AsyncSession:
    """Get a new TimescaleDB async session."""
    if not _TimescaleSessionLocal:
        raise RuntimeError("TimescaleDB session factory not initialized. Call init_timescale_connections first.")
    return _TimescaleSessionLocal()

def get_timescale_session_factory():
    """Returns the TimescaleDB session factory.
    Requires init_timescale_connections to have been called.
    """
    if not _TimescaleSessionLocal:
        raise RuntimeError("TimescaleDB session factory not initialized. Call init_timescale_connections first.")
    return _TimescaleSessionLocal

@asynccontextmanager
async def get_timescale_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a TimescaleDB session. 
    Requires init_timescale_connections to have been called.
    """
    session_factory = get_timescale_session_factory()
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        if session.in_transaction():
            await session.rollback()
        raise
    finally:
        await session.close()

async def close_timescale_connections():
    """Close TimescaleDB connections gracefully."""
    global _timescale_engine
    if _timescale_engine:
        await _timescale_engine.dispose()
        _timescale_engine = None
        logger.info("TimescaleDB connections closed") 