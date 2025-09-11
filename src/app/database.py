from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from typing import AsyncGenerator, Optional
from sqlalchemy import MetaData
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

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

    # Parse URL to extract SSL configuration
    parsed = urlparse(db_url)
    query_params = parse_qs(parsed.query)
    
    # Extract SSL parameters
    sslmode = query_params.get('sslmode', ['disable'])[0].lower()
    ssl_cert = query_params.get('sslcert', [None])[0]
    ssl_key = query_params.get('sslkey', [None])[0]
    ssl_ca = query_params.get('sslrootcert', [None])[0]
    
    # Remove SSL parameters from URL
    ssl_params = ['sslmode', 'sslcert', 'sslkey', 'sslrootcert']
    for param in ssl_params:
        query_params.pop(param, None)
    
    # Rebuild clean URL
    clean_query = urlencode(query_params, doseq=True) if query_params else ""
    clean_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        clean_query,
        parsed.fragment
    ))
    
    # Configure SSL based on mode
    connect_args = {}
    if sslmode in ['require', 'verify-ca', 'verify-full']:
        import ssl
        # Create SSL context
        ssl_context = ssl.create_default_context()
        
        if sslmode == 'require':
            # Require SSL but don't verify certificates (for self-signed certs)
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        elif sslmode in ['verify-ca', 'verify-full']:
            # Verify certificates
            ssl_context.check_hostname = (sslmode == 'verify-full')
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
        # Add certificate files if provided
        if ssl_cert and ssl_key:
            ssl_context.load_cert_chain(ssl_cert, ssl_key)
        if ssl_ca:
            ssl_context.load_verify_locations(ssl_ca)
            
        connect_args['ssl'] = ssl_context
    
    _async_engine = create_async_engine(clean_url, echo=echo_sql, connect_args=connect_args)
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