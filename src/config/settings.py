# src/config/settings.py
"""
Centralized configuration management.
Loads configuration from defaults, YAML file, and environment variables.
"""
import os
import yaml
import copy
import logging
from pathlib import Path

config_logger = logging.getLogger(__name__ + ".app_config_loader")

# --- Path Definitions ---
CONFIG_DIR = Path(__file__).resolve().parent  # src/config/
SRC_DIR = CONFIG_DIR.parent  # src/
PROJECT_ROOT = SRC_DIR.parent  # project root

CONFIG_FILE_PATH = PROJECT_ROOT / "config.yml"

# --- Default Prompts and Templates ---
DEFAULT_SYSTEM_PROMPT_FOR_REASONING = """You are an expert agricultural consultant specializing in plant pathology and nutrient management.
Your task is to analyze images of crops and provide detailed diagnostic information.
Focus on identifying:
1. Nutrient deficiencies (N, P, K, Ca, Mg, S, Fe, etc.)
2. Diseases (bacterial, fungal, viral)
3. Pest damage
4. Environmental stress (drought, heat, cold, etc.)
5. Growth stage assessment

Provide specific, actionable recommendations for farmers based on your observations.
Your analysis should be concise, technical but understandable, and focused on agricultural insights."""

DEFAULT_PROMPT_TEMPLATE_FOR_REASONING = """Image Caption: {caption}

Affected Area: Approximately {affected_percentage:.1f}% of the plant shows signs of stress or damage.

Based on this information, please provide:
1. A diagnosis of the most likely issues affecting this plant
2. Potential causes of these symptoms
3. Recommended treatments or interventions
4. Preventative measures for the future"""

# --- Default Application Configuration ---
DEFAULT_CONFIG = {
    "app": {
        "name": "AgroAI Crops Agent",
        "version": "0.2.0",
        "dev_mode": False,
        "cors_origins": [
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:8080",
        ]
    },
    "auth": {
        "secret_key": "super-secret-key-change-in-production",
        "algorithm": "HS256",
        "access_token_expire_minutes": 60
    },
    "chat_llm": {
        "model_name": "gemma:2b",
        "ollama_endpoint": "http://localhost:11434",
        "max_tokens": 2000,
        "temperature": 0.7,
        "system_prompt": "You are a helpful agricultural assistant."
    },
    "agent_llm": {
        "model_name": "gemma:2b",
        "ollama_endpoint": "http://localhost:11434",
        "system_prompt": "Eres un agente de Langchain para análisis agrícola. Puedes usar herramientas para responder preguntas.",
        "tools_enabled": ["get_report_history"],
        "tool_messages": {
            "reports_summary_header": "Aquí hay un resumen de los reportes más recientes:",
            "reports_summary_none_found": "No se encontraron reportes.",
            "report_detail_prefix": "- Reporte ID: {report_id}, Creado: {created_at}",
            "report_detail_crop": ", Cultivo: {crop_name}",
            "report_detail_image": ", Imagen: {image_filename}",
            "report_detail_finding": " - Hallazgo: {finding}",
            "report_detail_summary": " - Resumen: {summary}",
            "report_detail_no_details": " - (Detalles no disponibles)"
        }
    },
    "storage": {
        "base_data_path": str(PROJECT_ROOT / "temp_test_images") if (PROJECT_ROOT / "temp_test_images").is_dir() else "/tmp/agroai_images"
    },
    "analysis_services": {
        "unet": {
            "model_endpoint": "http://localhost:8080/predictions/unet-plants",
        },
        "blip": {
            "model_name": "Salesforce/blip2-opt-2.7b",
            "device": "cpu",
            "max_new_tokens": 50,
            "lightweight": False,
            "lightweight_model_name": "Salesforce/blip-image-captioning-base",
        },
        "blip_container": {
            "service_url": "http://localhost:8000",
            "timeout": 30,
            "use_container": False,
        },
        "reasoning_llm": {
            "model_name": "gemma:2b",
            "ollama_endpoint": "http://localhost:11434/api/generate",
            "max_tokens": 1000,
            "temperature": 0.7,
            "system_prompt": DEFAULT_SYSTEM_PROMPT_FOR_REASONING,
            "lightweight_model": "gemma:2b",
            "prompt_template": DEFAULT_PROMPT_TEMPLATE_FOR_REASONING,
        }
    },
    "database": {
        "url": "postgresql+asyncpg://genai_user:genai_password@localhost:54321/genai_reports_db",
        "echo": False
    },
    "timescale": {
        "url": "postgresql+asyncpg://genai_user:genai_password@localhost:54320/genai_reports_db",
        "echo": False
    },
    "weather_data": {
        "redis": {
            "host": "localhost",
            "port": 6379,
            "db": 0,
        },
        "cache": {
            "ttl": 3600,
        },
        "current_weather": {
            "cache_ttl": 900,
            "openweather_api_key": "",
        }
    },
    # Queue configuration (abstracted - can be redis, rabbitmq, kafka)
    "queues": {
        "backend": "redis",  # Options: redis, rabbitmq, memory
        "redis": {
            "host": "localhost",
            "port": 6379,
            "db": 1,  # Different DB than cache
        }
    },
    # Search configuration (Elasticsearch/OpenSearch)
    "search": {
        "backend": "elasticsearch",
        "elasticsearch": {
            "hosts": ["http://localhost:9200"],
            "index_summaries": "agro_summaries",
            "index_documents": "agro_documents",
        }
    },
    # Farm management defaults
    "farm_management": {
        "default_country": "AR",
    }
}


def load_app_config() -> dict:
    """
    Loads application configuration from defaults, YAML file, and environment variables.
    Also applies any dynamic adjustments like dev_mode settings.
    """
    # Start with a deep copy of default configurations
    config = copy.deepcopy(DEFAULT_CONFIG)

    # Load from YAML file
    try:
        with open(CONFIG_FILE_PATH, 'r') as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config:
                def deep_update(source, overrides):
                    for key, value in overrides.items():
                        if isinstance(value, dict) and key in source and isinstance(source[key], dict):
                            deep_update(source[key], value)
                        else:
                            source[key] = value
                    return source
                config = deep_update(config, yaml_config)
                config_logger.info(f"Successfully loaded and merged configuration from '{CONFIG_FILE_PATH}'.")
    except FileNotFoundError:
        config_logger.info(f"Configuration file '{CONFIG_FILE_PATH}' not found. Using defaults and environment variables.")
    except yaml.YAMLError as e:
        config_logger.error(f"Error parsing configuration file '{CONFIG_FILE_PATH}': {e}. Using defaults and environment variables.")

    # Override with environment variables
    _apply_env_overrides(config)

    # Apply DEV_MODE logic
    _apply_dev_mode_settings(config)

    config_logger.info("Application configuration loaded successfully.")
    return config


def _apply_env_overrides(config: dict):
    """Apply environment variable overrides to configuration."""
    # App config
    app_cfg = config.setdefault("app", {})
    app_cfg["name"] = os.environ.get("APP_NAME", app_cfg.get("name"))
    app_cfg["version"] = os.environ.get("APP_VERSION", app_cfg.get("version"))
    app_cfg["dev_mode"] = os.environ.get("DEV_MODE", str(app_cfg.get("dev_mode", False))).lower() == "true"
    app_cfg["cors_origins"] = os.environ.get("CORS_ORIGINS", ",".join(app_cfg.get("cors_origins", []))).split(",")
    if app_cfg["cors_origins"] == ['']:
        app_cfg["cors_origins"] = []

    # Auth config
    auth_cfg = config.setdefault("auth", {})
    auth_cfg["secret_key"] = os.environ.get("AUTH_SECRET_KEY", auth_cfg.get("secret_key"))
    auth_cfg["algorithm"] = os.environ.get("AUTH_ALGORITHM", auth_cfg.get("algorithm"))
    auth_cfg["access_token_expire_minutes"] = int(os.environ.get("AUTH_TOKEN_EXPIRE_MINUTES", auth_cfg.get("access_token_expire_minutes", 60)))

    # Storage config
    storage_cfg = config.setdefault("storage", {})
    storage_cfg["base_data_path"] = os.environ.get("BASE_DATA_PATH", storage_cfg.get("base_data_path"))
    abs_base_data_path = Path(storage_cfg["base_data_path"])
    if not abs_base_data_path.is_absolute():
        abs_base_data_path = PROJECT_ROOT / abs_base_data_path
    
    try:
        if not abs_base_data_path.exists():
            abs_base_data_path.mkdir(parents=True, exist_ok=True)
            config_logger.info(f"Created base data path directory: {abs_base_data_path}")
    except (PermissionError, OSError) as e:
        config_logger.warning(f"Could not create directory {abs_base_data_path}: {e}")
    
    storage_cfg["base_data_path"] = str(abs_base_data_path)

    # Chat LLM config
    chat_llm_cfg = config.setdefault("chat_llm", {})
    chat_llm_cfg["model_name"] = os.environ.get("CHAT_LLM_MODEL_NAME", chat_llm_cfg.get("model_name"))
    chat_llm_cfg["ollama_endpoint"] = os.environ.get("CHAT_OLLAMA_ENDPOINT", chat_llm_cfg.get("ollama_endpoint"))
    chat_llm_cfg["max_tokens"] = int(os.environ.get("CHAT_LLM_MAX_TOKENS", chat_llm_cfg.get("max_tokens", 0)))
    chat_llm_cfg["temperature"] = float(os.environ.get("CHAT_LLM_TEMPERATURE", chat_llm_cfg.get("temperature", 0.0)))
    chat_llm_cfg["system_prompt"] = os.environ.get("CHAT_LLM_SYSTEM_PROMPT", chat_llm_cfg.get("system_prompt"))

    # Agent LLM config
    agent_llm_cfg = config.setdefault("agent_llm", {})
    agent_llm_cfg["model_name"] = os.environ.get("AGENT_LLM_MODEL_NAME", agent_llm_cfg.get("model_name"))
    agent_llm_cfg["ollama_endpoint"] = os.environ.get("AGENT_OLLAMA_ENDPOINT", agent_llm_cfg.get("ollama_endpoint"))
    agent_llm_cfg["system_prompt"] = os.environ.get("AGENT_LLM_SYSTEM_PROMPT", agent_llm_cfg.get("system_prompt"))
    default_tools_str = ",".join(agent_llm_cfg.get("tools_enabled", []))
    agent_llm_cfg["tools_enabled"] = [t for t in os.environ.get("AGENT_LLM_TOOLS_ENABLED", default_tools_str).split(",") if t]

    # Analysis Services config
    analysis_services_cfg = config.setdefault("analysis_services", {})
    unet_cfg = analysis_services_cfg.setdefault("unet", {})
    unet_cfg["model_endpoint"] = os.environ.get("UNET_MODEL_ENDPOINT", unet_cfg.get("model_endpoint"))
    
    blip_cfg = analysis_services_cfg.setdefault("blip", {})
    blip_cfg["model_name"] = os.environ.get("BLIP_MODEL_NAME", blip_cfg.get("model_name"))
    blip_cfg["device"] = os.environ.get("BLIP_DEVICE", "cuda" if os.environ.get("USE_CUDA", "false").lower() == "true" else blip_cfg.get("device"))
    blip_cfg["max_new_tokens"] = int(os.environ.get("BLIP_MAX_NEW_TOKENS", blip_cfg.get("max_new_tokens", 0)))
    blip_cfg["lightweight"] = os.environ.get("BLIP_LIGHTWEIGHT", str(blip_cfg.get("lightweight", False))).lower() == "true"
    blip_cfg["lightweight_model_name"] = os.environ.get("BLIP_LIGHTWEIGHT_MODEL", blip_cfg.get("lightweight_model_name"))

    blip_container_cfg = analysis_services_cfg.setdefault("blip_container", {})
    blip_container_cfg["service_url"] = os.environ.get("BLIP_SERVICE_URL", blip_container_cfg.get("service_url"))
    blip_container_cfg["timeout"] = int(os.environ.get("BLIP_SERVICE_TIMEOUT", blip_container_cfg.get("timeout", 0)))
    blip_container_cfg["use_container"] = os.environ.get("USE_BLIP_CONTAINER", str(blip_container_cfg.get("use_container", False))).lower() == "true"

    reasoning_llm_cfg = analysis_services_cfg.setdefault("reasoning_llm", {})
    reasoning_llm_cfg["model_name"] = os.environ.get("LLM_MODEL_NAME", reasoning_llm_cfg.get("model_name"))
    reasoning_llm_cfg["ollama_endpoint"] = os.environ.get("OLLAMA_ENDPOINT", reasoning_llm_cfg.get("ollama_endpoint"))
    reasoning_llm_cfg["max_tokens"] = int(os.environ.get("LLM_MAX_TOKENS", reasoning_llm_cfg.get("max_tokens", 0)))
    reasoning_llm_cfg["temperature"] = float(os.environ.get("LLM_TEMPERATURE", reasoning_llm_cfg.get("temperature", 0.0)))
    reasoning_llm_cfg["system_prompt"] = os.environ.get("LLM_SYSTEM_PROMPT", reasoning_llm_cfg.get("system_prompt"))
    reasoning_llm_cfg["lightweight_model"] = os.environ.get("LLM_LIGHTWEIGHT_MODEL", reasoning_llm_cfg.get("lightweight_model"))
    reasoning_llm_cfg["prompt_template"] = os.environ.get("LLM_PROMPT_TEMPLATE", reasoning_llm_cfg.get("prompt_template"))

    # Database config
    db_cfg = config.setdefault("database", {})
    db_cfg["url"] = os.environ.get("DATABASE_URL", db_cfg.get("url"))
    db_cfg["echo"] = os.environ.get("DATABASE_ECHO_SQL", str(db_cfg.get("echo", False))).lower() == "true"

    # TimescaleDB config
    timescale_cfg = config.setdefault("timescale", {})
    timescale_cfg["url"] = os.environ.get("TIMESCALE_URL", timescale_cfg.get("url"))
    timescale_cfg["echo"] = os.environ.get("TIMESCALE_ECHO_SQL", str(timescale_cfg.get("echo", False))).lower() == "true"

    # Weather Data config
    weather_data_cfg = config.setdefault("weather_data", {})
    redis_cfg = weather_data_cfg.setdefault("redis", {})
    redis_cfg["host"] = os.environ.get("REDIS_HOST", redis_cfg.get("host"))
    redis_cfg["port"] = int(os.environ.get("REDIS_PORT", redis_cfg.get("port", 6379)))
    redis_cfg["db"] = int(os.environ.get("REDIS_DB", redis_cfg.get("db", 0)))
    cache_cfg = weather_data_cfg.setdefault("cache", {})
    cache_cfg["ttl"] = int(os.environ.get("WEATHER_CACHE_TTL", cache_cfg.get("ttl", 3600)))
    current_weather_cfg = weather_data_cfg.setdefault("current_weather", {})
    current_weather_cfg["cache_ttl"] = int(os.environ.get("CURRENT_WEATHER_CACHE_TTL", current_weather_cfg.get("cache_ttl", 900)))
    current_weather_cfg["openweather_api_key"] = os.environ.get("OPENWEATHER_API_KEY", current_weather_cfg.get("openweather_api_key"))

    # Search config
    search_cfg = config.setdefault("search", {})
    search_cfg["backend"] = os.environ.get("SEARCH_BACKEND", search_cfg.get("backend", "elasticsearch"))
    es_cfg = search_cfg.setdefault("elasticsearch", {})
    es_hosts = os.environ.get("ELASTICSEARCH_HOSTS")
    if es_hosts:
        es_cfg["hosts"] = es_hosts.split(",")


def _apply_dev_mode_settings(config: dict):
    """Apply development mode specific settings."""
    dev_mode = config.get("app", {}).get("dev_mode", False)
    if not dev_mode:
        return

    blip_cfg = config.get("analysis_services", {}).get("blip", {})
    if not blip_cfg.get("lightweight"):
        blip_cfg["lightweight"] = True
        blip_cfg["model_name"] = blip_cfg.get("lightweight_model_name")

    blip_container_cfg = config.get("analysis_services", {}).get("blip_container", {})
    if os.environ.get("USE_BLIP_CONTAINER") is None:
        blip_container_cfg["use_container"] = True

    reasoning_llm_cfg = config.get("analysis_services", {}).get("reasoning_llm", {})
    if reasoning_llm_cfg.get("model_name") == "mistral":
        reasoning_llm_cfg["model_name"] = reasoning_llm_cfg.get("lightweight_model")
        reasoning_llm_cfg["max_tokens"] = min(reasoning_llm_cfg.get("max_tokens", 500), 500)
