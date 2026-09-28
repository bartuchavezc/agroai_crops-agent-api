"""
Centralized configuration: defaults, then optional config.yml, then environment variables.
"""
import copy
import logging
import os
from pathlib import Path

import yaml

config_logger = logging.getLogger(__name__ + ".app_config_loader")

CONFIG_DIR = Path(__file__).resolve().parent
SRC_DIR = CONFIG_DIR.parent
PROJECT_ROOT = SRC_DIR.parent
CONFIG_FILE_PATH = PROJECT_ROOT / "config.yml"

DEV_SECRET_KEY = "dev-only-secret-key-change-me"
# Valid Fernet key used only when DEV_MODE=true and none is configured.
DEV_ENCRYPTION_KEY = "ZGV2LW9ubHktZW5jcnlwdGlvbi1rZXktMzJieXRlcyE="

DEFAULT_CONFIG = {
    "app": {
        "name": "AgroAI Crops Agent",
        "version": "0.3.0",
        "dev_mode": False,
        "timezone": "America/Argentina/Buenos_Aires",
        "cors_origins": [
            "http://localhost:3000",
            "http://localhost:8081",
            "http://localhost:19006",
        ],
    },
    "auth": {
        "secret_key": "",
        "algorithm": "HS256",
        "access_token_expire_minutes": 60 * 24,
        # Off in production (see .env.example / deploy/.env.example): the family account is created by
        # hand once; every other user is added via POST /auth/users (owner-only "add member").
        "allow_public_signup": True,
    },
    "security": {
        "credentials_encryption_key": "",
    },
    "database": {
        "url": "postgresql+asyncpg://agroai:agroai@localhost:54321/agroai",
        "echo": False,
    },
    "gemini": {
        "model": "gemini-flash-latest",
        # Tried in order when the primary answers 429/5xx (free tier gets overloaded at peaks).
        "fallback_models": ["gemini-3.5-flash", "gemini-3-flash-preview"],
        "lite_model": "gemini-flash-lite-latest",
        "embedding_model": "gemini-embedding-001",
        "embedding_dimensions": 768,
        "max_image_side": 1536,
    },
    "storage": {
        "base_data_path": str(PROJECT_ROOT / "data" / "uploads"),
    },
    "weather": {
        "openweather_api_key": "",
        "current_cache_ttl": 900,
        "smn": {
            "enabled": True,
            "horizon_hours": 72,
            "hourly_step": 3,
            "interval_hours": 6,
            "grid_cache_dir": str(PROJECT_ROOT / "data" / "smn_cache"),
        },
    },
    "farm_management": {
        "default_country": "AR",
    },
    "search": {
        # Server-side, not BYOK: web search is a shared service, independent of each user's Gemini quota.
        "tavily_api_key": "",
    },
    "satellite": {
        # Copernicus Data Space Ecosystem (free tier, 10k processing credits/month). Zone-level NDVI/NDWI
        # signal degrades gracefully (feature reports "not configured") when these are unset.
        "copernicus_client_id": "",
        "copernicus_client_secret": "",
    },
}


def _deep_update(source: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(source.get(key), dict):
            _deep_update(source[key], value)
        else:
            source[key] = value
    return source


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_app_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)

    if CONFIG_FILE_PATH.exists():
        try:
            yaml_config = yaml.safe_load(CONFIG_FILE_PATH.read_text()) or {}
            _deep_update(config, yaml_config)
        except yaml.YAMLError as e:
            config_logger.error(f"Error parsing {CONFIG_FILE_PATH}: {e}")

    _apply_env_overrides(config)
    _validate(config)
    return config


def _apply_env_overrides(config: dict) -> None:
    env = os.environ.get

    app = config["app"]
    app["name"] = env("APP_NAME", app["name"])
    app["dev_mode"] = _env_bool("DEV_MODE", app["dev_mode"])
    app["timezone"] = env("APP_TIMEZONE", app["timezone"])
    if env("CORS_ORIGINS") is not None:
        app["cors_origins"] = [o.strip() for o in env("CORS_ORIGINS").split(",") if o.strip()]

    auth = config["auth"]
    auth["secret_key"] = env("AUTH_SECRET_KEY", auth["secret_key"])
    auth["access_token_expire_minutes"] = int(
        env("AUTH_TOKEN_EXPIRE_MINUTES", auth["access_token_expire_minutes"])
    )
    auth["allow_public_signup"] = _env_bool("ALLOW_PUBLIC_SIGNUP", auth["allow_public_signup"])

    security = config["security"]
    security["credentials_encryption_key"] = env(
        "CREDENTIALS_ENCRYPTION_KEY", security["credentials_encryption_key"]
    )

    db = config["database"]
    db["url"] = env("DATABASE_URL", db["url"])
    db["echo"] = _env_bool("DATABASE_ECHO_SQL", db["echo"])

    gemini = config["gemini"]
    gemini["model"] = env("GEMINI_MODEL", gemini["model"])
    gemini["lite_model"] = env("GEMINI_LITE_MODEL", gemini["lite_model"])
    if env("GEMINI_FALLBACK_MODELS") is not None:
        gemini["fallback_models"] = [m.strip() for m in env("GEMINI_FALLBACK_MODELS").split(",") if m.strip()]
    gemini["embedding_model"] = env("GEMINI_EMBEDDING_MODEL", gemini["embedding_model"])

    storage = config["storage"]
    storage["base_data_path"] = env("BASE_DATA_PATH", storage["base_data_path"])

    weather = config["weather"]
    weather["openweather_api_key"] = env("OPENWEATHER_API_KEY", weather["openweather_api_key"])
    weather["current_cache_ttl"] = int(env("CURRENT_WEATHER_CACHE_TTL", weather["current_cache_ttl"]))
    smn = weather["smn"]
    smn["enabled"] = _env_bool("SMN_ENABLED", smn["enabled"])
    smn["hourly_step"] = int(env("SMN_HOURLY_STEP", smn["hourly_step"]))
    smn["interval_hours"] = int(env("SMN_INTERVAL_HOURS", smn["interval_hours"]))
    smn["grid_cache_dir"] = env("SMN_GRID_CACHE_DIR", smn["grid_cache_dir"])

    search = config["search"]
    search["tavily_api_key"] = env("TAVILY_API_KEY", search["tavily_api_key"])

    satellite = config["satellite"]
    satellite["copernicus_client_id"] = env("COPERNICUS_CLIENT_ID", satellite["copernicus_client_id"])
    satellite["copernicus_client_secret"] = env("COPERNICUS_CLIENT_SECRET", satellite["copernicus_client_secret"])


def _validate(config: dict) -> None:
    dev_mode = config["app"]["dev_mode"]
    auth = config["auth"]
    security = config["security"]

    if not auth["secret_key"]:
        if not dev_mode:
            raise ValueError("AUTH_SECRET_KEY must be set when DEV_MODE is false.")
        config_logger.warning("AUTH_SECRET_KEY not set; using an insecure development key.")
        auth["secret_key"] = DEV_SECRET_KEY

    if not security["credentials_encryption_key"]:
        if not dev_mode:
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY must be set when DEV_MODE is false.")
        config_logger.warning("CREDENTIALS_ENCRYPTION_KEY not set; using an insecure development key.")
        security["credentials_encryption_key"] = DEV_ENCRYPTION_KEY

    if not dev_mode and "*" in config["app"]["cors_origins"]:
        raise ValueError("CORS_ORIGINS cannot contain '*' when DEV_MODE is false.")
