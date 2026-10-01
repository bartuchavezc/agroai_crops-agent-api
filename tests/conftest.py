"""
Test setup. Unit tests need nothing; integration tests (marked by the `client`/`container` fixtures)
run against a real PostgreSQL + TimescaleDB + pgvector: by default the compose `db` service on
localhost:54321, database `agroai_test` (created and migrated automatically).

    docker compose up -d db && uv run pytest
"""
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get("TEST_ADMIN_DSN", "postgresql://agroai:agroai@localhost:54321/postgres")
TEST_DB = os.environ.get("TEST_DB_NAME", "agroai_test")
TEST_DATABASE_URL = ADMIN_URL.rsplit("/", 1)[0].replace("postgresql://", "postgresql+asyncpg://") + f"/{TEST_DB}"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["DEV_MODE"] = "true"
os.environ["ALLOW_PUBLIC_SIGNUP"] = "true"
os.environ.setdefault("BASE_DATA_PATH", str(ROOT / "data" / "test_uploads"))
os.environ.setdefault("OPENWEATHER_API_KEY", "")
os.environ["PLATFORM_ADMIN_EMAILS"] = "Platform-Admin@example.com"


async def _ensure_database() -> bool:
    import asyncpg

    try:
        conn = await asyncpg.connect(ADMIN_URL, timeout=3)
    except (OSError, asyncpg.PostgresError):
        return False
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB)
        if exists:
            await conn.execute(f'DROP DATABASE "{TEST_DB}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DB}"')
    finally:
        await conn.close()
    return True


@pytest.fixture(scope="session")
def database() -> str:
    if not asyncio.run(_ensure_database()):
        pytest.skip("PostgreSQL test database not reachable (run `docker compose up -d db`).")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
        capture_output=True,
    )
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def app(database):
    from src.main import create_app

    return create_app()


@pytest.fixture(scope="session")
def container(app):
    return app.state.container


@pytest.fixture(scope="session")
async def client(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _signup(client, email_prefix: str = "user") -> Dict[str, Any]:
    email = f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": "secret-pass-1", "first_name": "Ana"}
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    return {"email": email, "headers": headers, "user": me["user"], "account": me["account"]}


@pytest.fixture
def signup(client):
    async def _make(prefix: str = "user"):
        return await _signup(client, prefix)
    return _make


@pytest.fixture
def add_member(client):
    async def _add(owner: Dict[str, Any], role: str = "staff") -> Dict[str, Any]:
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        response = await client.post(
            "/api/v1/auth/users",
            headers=owner["headers"],
            json={"email": email, "password": "secret-pass-1", "role": role},
        )
        assert response.status_code == 201, response.text
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": "secret-pass-1"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = (await client.get("/api/v1/auth/me", headers=headers)).json()
        return {"email": email, "headers": headers, "user": me["user"], "account": me["account"]}
    return _add


# ---------- plain dict fixtures used by the unit tests ----------

@pytest.fixture
def weather_context() -> Dict[str, Any]:
    """Sample weather context for testing rules engine."""
    return {
        "temperature": 25,
        "humidity": 60,
        "wind_speed": 10,
        "precipitation": 0,
    }


@pytest.fixture
def cold_weather_context() -> Dict[str, Any]:
    """Cold weather context for testing cold stress rules."""
    return {
        "temperature": 2,
        "humidity": 45,
        "wind_speed": 15,
        "precipitation": 0,
    }


@pytest.fixture
def hot_weather_context() -> Dict[str, Any]:
    """Hot weather context for testing heat stress rules."""
    return {
        "temperature": 38,
        "humidity": 30,
        "wind_speed": 5,
        "precipitation": 0,
    }


@pytest.fixture
def fungal_risk_context() -> Dict[str, Any]:
    """High humidity + warm context for fungal risk testing."""
    return {
        "temperature": 22,
        "humidity": 90,
        "wind_speed": 2,
        "precipitation": 5,
    }


@pytest.fixture
def affected_plant_context() -> Dict[str, Any]:
    """Context with affected plant percentage."""
    return {
        "temperature": 25,
        "humidity": 60,
        "affected_percentage": 55,
    }


@pytest.fixture
def sample_user_data() -> Dict[str, Any]:
    """Sample user data for auth testing."""
    return {
        "id": "user-123",
        "email": "test@example.com",
        "password_hash": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.qJ3tVq7Aq5y6Ey",  # "password123"
    }


@pytest.fixture
def auth_config() -> Dict[str, Any]:
    """Sample auth configuration."""
    return {
        "secret_key": "test-secret-key-for-testing-only-32+bytes",
        "algorithm": "HS256",
        "access_token_expire_minutes": 30,
    }
