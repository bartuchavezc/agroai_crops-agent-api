# src/app/config/core.py
import os
import yaml
from pathlib import Path
import logging
import copy # For deepcopy

from .default_settings import DEFAULT_CONFIG, PROJECT_ROOT

config_logger = logging.getLogger(__name__ + ".app_config_loader")

CONFIG_FILE_PATH = PROJECT_ROOT / "config.yml"

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
                # Deep merge yaml_config into config
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
    # App config
    app_cfg = config.setdefault("app", {})
    app_cfg["name"] = os.environ.get("APP_NAME", app_cfg.get("name"))
    app_cfg["version"] = os.environ.get("APP_VERSION", app_cfg.get("version"))
    app_cfg["dev_mode"] = os.environ.get("DEV_MODE", str(app_cfg.get("dev_mode", False))).lower() == "true"
    app_cfg["cors_origins"] = os.environ.get("CORS_ORIGINS", ",".join(app_cfg.get("cors_origins", []))).split(",")
    if app_cfg["cors_origins"] == [''] and not DEFAULT_CONFIG.get("app",{}).get("cors_origins"): # Handle empty string from env if default was empty
        app_cfg["cors_origins"] = []

    # Storage config
    storage_cfg = config.setdefault("storage", {})
    storage_cfg["base_data_path"] = os.environ.get("BASE_DATA_PATH", storage_cfg.get("base_data_path"))
    abs_base_data_path = Path(storage_cfg["base_data_path"])
    if not abs_base_data_path.is_absolute():
        abs_base_data_path = PROJECT_ROOT / abs_base_data_path
    
    # Try to create directory only if we have write permissions
    try:
        if not abs_base_data_path.exists():
            abs_base_data_path.mkdir(parents=True, exist_ok=True)
            config_logger.info(f"Created base data path directory: {abs_base_data_path}")
    except (PermissionError, OSError) as e:
        config_logger.warning(f"Could not create directory {abs_base_data_path}: {e}")
        config_logger.info(f"Using existing path: {abs_base_data_path}")
    
    storage_cfg["base_data_path"] = str(abs_base_data_path)

    # Chat LLM config
    chat_llm_cfg = config.setdefault("chat_llm", {})
    chat_llm_cfg["model_name"] = os.environ.get("CHAT_LLM_MODEL_NAME", chat_llm_cfg.get("model_name"))
    chat_llm_cfg["ollama_endpoint"] = os.environ.get("CHAT_OLLAMA_ENDPOINT", chat_llm_cfg.get("ollama_endpoint"))
    chat_llm_cfg["max_tokens"] = int(os.environ.get("CHAT_LLM_MAX_TOKENS", chat_llm_cfg.get("max_tokens", 0)))
    chat_llm_cfg["temperature"] = float(os.environ.get("CHAT_LLM_TEMPERATURE", chat_llm_cfg.get("temperature", 0.0)))
    chat_llm_cfg["system_prompt"] = os.environ.get("CHAT_LLM_SYSTEM_PROMPT", chat_llm_cfg.get("system_prompt"))

    # Agent LLM config (New)
    agent_llm_cfg = config.setdefault("agent_llm", {})
    agent_llm_cfg["model_name"] = os.environ.get("AGENT_LLM_MODEL_NAME", agent_llm_cfg.get("model_name"))
    agent_llm_cfg["ollama_endpoint"] = os.environ.get("AGENT_OLLAMA_ENDPOINT", agent_llm_cfg.get("ollama_endpoint"))
    agent_llm_cfg["system_prompt"] = os.environ.get("AGENT_LLM_SYSTEM_PROMPT", agent_llm_cfg.get("system_prompt"))
    # For tools_enabled, it's a list. Env var should be comma-separated string.
    default_tools_str = ",".join(agent_llm_cfg.get("tools_enabled", []))
    agent_llm_cfg["tools_enabled"] = os.environ.get("AGENT_LLM_TOOLS_ENABLED", default_tools_str).split(",")
    # Handle empty string from env if default was empty or only had empty strings
    if agent_llm_cfg["tools_enabled"] == [''] and not DEFAULT_CONFIG.get("agent_llm",{}).get("tools_enabled",[]):
        agent_llm_cfg["tools_enabled"] = []
    else:
        # Filter out empty strings that might result from split(',') if the env var is empty or ends with a comma
        agent_llm_cfg["tools_enabled"] = [tool for tool in agent_llm_cfg["tools_enabled"] if tool]
    # Load tool_messages (assuming it's a dict, not overridden by simple env var directly, but through yaml or defaults)
    agent_llm_cfg["tool_messages"] = agent_llm_cfg.get("tool_messages", DEFAULT_CONFIG.get("agent_llm", {}).get("tool_messages", {}))

    # Analysis Services config
    analysis_services_cfg = config.setdefault("analysis_services", {})
    # UNET
    unet_cfg = analysis_services_cfg.setdefault("unet", {})
    unet_cfg["model_endpoint"] = os.environ.get("UNET_MODEL_ENDPOINT", unet_cfg.get("model_endpoint"))
    
    # BLIP
    blip_cfg = analysis_services_cfg.setdefault("blip", {})
    blip_cfg["model_name"] = os.environ.get("BLIP_MODEL_NAME", blip_cfg.get("model_name"))
    blip_cfg["device"] = os.environ.get("BLIP_DEVICE", "cuda" if os.environ.get("USE_CUDA", "false").lower() == "true" else blip_cfg.get("device"))
    blip_cfg["max_new_tokens"] = int(os.environ.get("BLIP_MAX_NEW_TOKENS", blip_cfg.get("max_new_tokens", 0)))
    blip_cfg["lightweight"] = os.environ.get("BLIP_LIGHTWEIGHT", str(blip_cfg.get("lightweight", False))).lower() == "true"
    blip_cfg["lightweight_model_name"] = os.environ.get("BLIP_LIGHTWEIGHT_MODEL", blip_cfg.get("lightweight_model_name"))

    # BLIP Container
    blip_container_cfg = analysis_services_cfg.setdefault("blip_container", {})
    blip_container_cfg["service_url"] = os.environ.get("BLIP_SERVICE_URL", blip_container_cfg.get("service_url"))
    blip_container_cfg["timeout"] = int(os.environ.get("BLIP_SERVICE_TIMEOUT", blip_container_cfg.get("timeout", 0)))
    blip_container_cfg["use_container"] = os.environ.get("USE_BLIP_CONTAINER", str(blip_container_cfg.get("use_container", False))).lower() == "true"

    # Reasoning LLM
    reasoning_llm_cfg = analysis_services_cfg.setdefault("reasoning_llm", {})
    reasoning_llm_cfg["model_name"] = os.environ.get("LLM_MODEL_NAME", reasoning_llm_cfg.get("model_name")) # Note: LLM_MODEL_NAME might conflict if chat and reasoning use same env var
    reasoning_llm_cfg["ollama_endpoint"] = os.environ.get("OLLAMA_ENDPOINT", reasoning_llm_cfg.get("ollama_endpoint")) # Same potential conflict
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
    # Redis config
    redis_cfg = weather_data_cfg.setdefault("redis", {})
    redis_cfg["host"] = os.environ.get("REDIS_HOST", redis_cfg.get("host"))
    redis_cfg["port"] = int(os.environ.get("REDIS_PORT", redis_cfg.get("port", 6379)))
    redis_cfg["db"] = int(os.environ.get("REDIS_DB", redis_cfg.get("db", 0)))
    # Cache config
    cache_cfg = weather_data_cfg.setdefault("cache", {})
    cache_cfg["ttl"] = int(os.environ.get("WEATHER_CACHE_TTL", cache_cfg.get("ttl", 3600)))
    
    # Current Weather config (OpenWeatherMap)
    current_weather_cfg = weather_data_cfg.setdefault("current_weather", {})
    current_weather_cfg["cache_ttl"] = int(os.environ.get("CURRENT_WEATHER_CACHE_TTL", current_weather_cfg.get("cache_ttl", 900)))
    current_weather_cfg["openweather_api_key"] = os.environ.get("OPENWEATHER_API_KEY", current_weather_cfg.get("openweather_api_key"))

    # Apply DEV_MODE logic
    dev_mode = app_cfg["dev_mode"]
    if dev_mode:
        if not blip_cfg.get("lightweight"): # Check if key exists
            blip_cfg["lightweight"] = True
            blip_cfg["model_name"] = blip_cfg.get("lightweight_model_name")
        
        if os.environ.get("USE_BLIP_CONTAINER") is None: # Check env var directly for this specific logic
            blip_container_cfg["use_container"] = True
            
        if reasoning_llm_cfg.get("model_name") == "mistral": # Check if key exists
            reasoning_llm_cfg["model_name"] = reasoning_llm_cfg.get("lightweight_model")
            reasoning_llm_cfg["max_tokens"] = min(reasoning_llm_cfg.get("max_tokens", 500), 500)

    config_logger.info("Application configuration loaded successfully.")
    return config 