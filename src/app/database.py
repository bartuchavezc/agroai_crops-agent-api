from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator, Optional
from sqlalchemy import MetaData

# Define shared_metadata FIRST, before other imports that might depend on it indirectly.
shared_metadata = MetaData()

# Globals to be initialized by init_database_config
_async_engine: Optional[create_async_engine] = None
_AsyncSessionLocal: Optional[async_sessionmaker[AsyncSession]] = None

def init_database_connections(db_url: str, echo_sql: bool):
    """Initializes the database engine and session factory.
    This should be called once at application startup after config is loaded.
    """
    global _async_engine, _AsyncSessionLocal
    if _async_engine is not None:
        return

    _async_engine = create_async_engine(db_url, echo=echo_sql)
    _AsyncSessionLocal = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )

async def init_db_tables():
    """Creates database tables if they don't exist.
    Requires init_database_connections to have been called.
    """
    if not _async_engine:
        raise RuntimeError("Database engine not initialized. Call init_database_connections first.")
    
    async with _async_engine.begin() as conn:
        # Only create tables if they don't exist. Do NOT drop tables/data on startup.
        await conn.run_sync(shared_metadata.create_all)

def get_session_factory():
    """Returns the session factory.
    Requires init_database_connections to have been called.
    """
    if not _AsyncSessionLocal:
        raise RuntimeError("Database session factory not initialized. Call init_database_connections first.")
    return _AsyncSessionLocal

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a database session. 
    Requires init_database_connections to have been called.
    """
    session_factory = get_session_factory()
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