# Shared database module
from .postgres import (
    init_database_connections,
    init_db_tables,
    get_session_factory,
    get_db_session,
    shared_metadata,
)
from .timescale import (
    init_timescale_connections,
    init_timescale_tables,
    get_timescale_session_factory,
    get_timescale_session,
    timescale_metadata,
)

__all__ = [
    # Postgres
    "init_database_connections",
    "init_db_tables",
    "get_session_factory",
    "get_db_session",
    "shared_metadata",
    # TimescaleDB
    "init_timescale_connections",
    "init_timescale_tables",
    "get_timescale_session_factory",
    "get_timescale_session",
    "timescale_metadata",
]
