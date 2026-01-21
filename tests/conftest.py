# tests/conftest.py
"""
Shared pytest fixtures and configuration.
"""
import pytest
from datetime import datetime
from typing import Dict, Any


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
        "secret_key": "test-secret-key-for-testing-only",
        "algorithm": "HS256",
        "access_token_expire_minutes": 30,
    }
