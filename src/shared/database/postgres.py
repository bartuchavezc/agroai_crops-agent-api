"""
PostgreSQL (TimescaleDB + pgvector) connection management. One database for everything.
"""
import ssl
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

shared_metadata = MetaData(naming_convention=NAMING_CONVENTION)
Base = declarative_base(metadata=shared_metadata)

ADK_SCHEMA = "adk"

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None
_adk_engine: Optional[AsyncEngine] = None


def parse_db_url(db_url: str) -> tuple[str, dict]:
    """Strip libpq-style ssl* query params (unsupported by asyncpg) and turn them into connect_args."""
    parsed = urlparse(db_url)
    query = parse_qs(parsed.query)
    sslmode = query.pop("sslmode", ["disable"])[0].lower()
    ssl_cert = query.pop("sslcert", [None])[0]
    ssl_key = query.pop("sslkey", [None])[0]
    ssl_ca = query.pop("sslrootcert", [None])[0]
    clean_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    connect_args: dict = {}
    if sslmode in {"require", "verify-ca", "verify-full"}:
        ctx = ssl.create_default_context()
        if sslmode == "require":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = sslmode == "verify-full"
            ctx.verify_mode = ssl.CERT_REQUIRED
        if ssl_cert and ssl_key:
            ctx.load_cert_chain(ssl_cert, ssl_key)
        if ssl_ca:
            ctx.load_verify_locations(ssl_ca)
        connect_args["ssl"] = ctx
    return clean_url, connect_args


def init_database_connections(db_url: str, echo_sql: bool = False) -> None:
    global _engine, _session_factory, _adk_engine
    if _engine is not None:
        return
    clean_url, connect_args = parse_db_url(db_url)
    _engine = create_async_engine(clean_url, echo=echo_sql, connect_args=connect_args, pool_pre_ping=True)
    _session_factory = async_sessionmaker(bind=_engine, class_=AsyncSession, expire_on_commit=False)

    adk_args = {**connect_args, "server_settings": {"search_path": ADK_SCHEMA}}
    _adk_engine = create_async_engine(clean_url, echo=echo_sql, connect_args=adk_args, pool_pre_ping=True)


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_database_connections first.")
    return _engine


def get_adk_engine() -> AsyncEngine:
    if _adk_engine is None:
        raise RuntimeError("Database not initialized. Call init_database_connections first.")
    return _adk_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_database_connections first.")
    return _session_factory


async def dispose_database_connections() -> None:
    global _engine, _session_factory, _adk_engine
    for engine in (_engine, _adk_engine):
        if engine is not None:
            await engine.dispose()
    _engine = _session_factory = _adk_engine = None
