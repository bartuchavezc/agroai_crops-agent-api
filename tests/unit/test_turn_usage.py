from google.genai import types

from src.agent.providers.gemini import GeminiGateway
from src.agent.usage import TurnUsage
from src.config.settings import load_app_config


def _meta(prompt, cached, out, thoughts=None):
    return types.GenerateContentResponseUsageMetadata(
        prompt_token_count=prompt, cached_content_token_count=cached,
        candidates_token_count=out, thoughts_token_count=thoughts,
    )


def test_usage_accumulates_complete_responses_and_ignores_missing_metadata():
    usage = TurnUsage()
    usage.add(None)
    assert not usage.seen
    usage.add(_meta(1000, 0, 30, 10))
    usage.add(_meta(1200, 900, 60))  # None counts (no cache, no thinking) are zero
    assert (usage.llm_calls, usage.prompt_tokens, usage.cached_tokens) == (2, 2200, 900)
    assert (usage.output_tokens, usage.thinking_tokens) == (90, 10)
    assert "llm_calls=2" in usage.log_line("c-1", "m") and "cached_tokens=900" in usage.log_line("c-1", "m")


def _gateway(**gemini):
    config = {"model": "m", "lite_model": "l", "embedding_model": "e", "embedding_dimensions": 768, **gemini}
    return GeminiGateway(credentials_service=None, config=config)


def test_generation_config_leaves_temperature_to_the_model_and_sets_thinking():
    default = _gateway().chat_generation_config()
    assert default.temperature is None and default.thinking_config is None  # nothing configured -> model defaults
    tuned = _gateway(chat_thinking_level="Medium", chat_temperature=0.7).chat_generation_config()
    assert tuned.temperature == 0.7 and tuned.thinking_config.thinking_level.value == "MEDIUM"
    assert _gateway(chat_thinking_level="").chat_generation_config().thinking_config is None


def test_env_overrides_for_cache_thinking_and_temperature(monkeypatch):
    base = load_app_config()["gemini"]
    assert base["explicit_cache"] is False and base["chat_thinking_level"] == "low" and base["chat_temperature"] is None
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "true")
    monkeypatch.setenv("GEMINI_CHAT_THINKING_LEVEL", "high")
    monkeypatch.setenv("GEMINI_CHAT_TEMPERATURE", "0.9")
    tuned = load_app_config()["gemini"]
    assert tuned["explicit_cache"] is True and tuned["chat_thinking_level"] == "high"
    assert tuned["chat_temperature"] == 0.9
