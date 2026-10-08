"""
Alembic migrations for the single AgroAI database (TimescaleDB + pgvector).
Tables of the `adk` schema belong to Google ADK's session service and are not managed here.
"""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine

from src.shared.database import parse_db_url, shared_metadata

# Import every model module so its tables register on shared_metadata.
import src.agent.conversations.models  # noqa: F401,E402
import src.agent.memory.models  # noqa: F401,E402
import src.agent.providers.models  # noqa: F401,E402
import src.application.alerts.models  # noqa: F401,E402
import src.application.farm.models  # noqa: F401,E402
import src.application.inventory.models  # noqa: F401,E402
import src.application.management.models  # noqa: F401,E402
import src.application.notifications.models  # noqa: F401,E402
import src.application.planning.models  # noqa: F401,E402
import src.application.products.models  # noqa: F401,E402
import src.application.reports.repository  # noqa: F401,E402
import src.application.satellite.models  # noqa: F401,E402
import src.application.soil_data.grid_models  # noqa: F401,E402
import src.auth.domain.models  # noqa: F401,E402
import src.providers.weather.models  # noqa: F401,E402

load_dotenv()
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = shared_metadata
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agroai:agroai@localhost:54321/agroai")


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in (None, "public")
    if type_ == "index" and name and name.endswith("_time_idx"):
        return False  # created automatically by create_hypertable
    return True


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    url, connect_args = parse_db_url(DATABASE_URL)
    engine = create_async_engine(url, connect_args=connect_args)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_offline():
    context.configure(url=parse_db_url(DATABASE_URL)[0], target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
