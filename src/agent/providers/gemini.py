"""
Gemini access with per-user API keys (BYOK). Nothing here ever reads GOOGLE_API_KEY from
the environment: every client is built from the calling user's own key.
"""
import hashlib
import logging
from typing import Any, Optional, Sequence, Type, TypeVar
from uuid import UUID

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from src.shared.utils.errors import (
    CropAnalysisError,
    ProviderError,
    ProviderKeyInvalidError,
    ProviderQuotaExceededError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PROVIDER_GEMINI = "gemini"

# Free-tier models return 503 under load and 429 on bursts; retry with backoff before giving up.
RETRYABLE_STATUS = (429, 500, 502, 503, 504)
RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=2, initial_delay=1.0, max_delay=8.0, http_status_codes=list(RETRYABLE_STATUS)
)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, genai_errors.APIError) and getattr(exc, "code", None) in RETRYABLE_STATUS


def build_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(retry_options=RETRY_OPTIONS))


def translate_provider_error(exc: BaseException) -> CropAnalysisError:
    """Map google-genai errors to API errors the clients understand."""
    if isinstance(exc, CropAnalysisError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None)
        status = (getattr(exc, "status", "") or "").upper()
        message = (getattr(exc, "message", "") or "").lower()
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return ProviderQuotaExceededError()
        if code in (401, 403) or "api key" in message or status in {"UNAUTHENTICATED", "PERMISSION_DENIED"}:
            return ProviderKeyInvalidError()
        if code in (500, 502, 503, 504) or status == "UNAVAILABLE":
            return ProviderError("Gemini is overloaded right now. Try again in a moment.")
        return ProviderError(f"Gemini error {code} {status}")
    return ProviderError(f"Gemini request failed: {type(exc).__name__}")


def error_from_event(error_code: str, error_message: Optional[str]) -> CropAnalysisError:
    """ADK reports model failures as events (error_code/error_message) instead of raising."""
    text = f"{error_code} {error_message or ''}".upper()
    if "RESOURCE_EXHAUSTED" in text or "429" in text:
        return ProviderQuotaExceededError()
    if "API KEY" in text or "PERMISSION_DENIED" in text or "UNAUTHENTICATED" in text:
        return ProviderKeyInvalidError()
    if "UNAVAILABLE" in text or "503" in text:
        return ProviderError("Gemini is overloaded right now. Try again in a moment.")
    if "SAFETY" in text or "BLOCK" in text:
        return ProviderError("The model declined to answer this message.")
    return ProviderError(f"The model stopped unexpectedly ({error_code}).")


async def validate_gemini_key(api_key: str) -> None:
    """Cheap check: listing models does not consume generation quota."""
    client = genai.Client(api_key=api_key)
    try:
        pager = await client.aio.models.list(config={"page_size": 1})
        async for _ in pager:
            break
    except Exception as exc:  # noqa: BLE001 - translated below
        raise translate_provider_error(exc) from None


class GeminiGateway:
    """Builds per-user clients and wraps the one-shot calls used outside the agent loop."""

    def __init__(self, credentials_service, config: dict):
        self.credentials = credentials_service
        self.model = config["model"]
        self.fallback_models = list(config.get("fallback_models") or [])
        self.chat_model = config.get("chat_model") or self.model
        self.chat_fallback_models = list(config.get("chat_fallback_models") or [])
        self.lite_model = config["lite_model"]
        self.embedding_model = config["embedding_model"]
        self.embedding_dimensions = int(config["embedding_dimensions"])
        self.explicit_cache = bool(config.get("explicit_cache", False))
        self.chat_thinking_level = (config.get("chat_thinking_level") or "").strip().lower()
        self.chat_temperature = config.get("chat_temperature")
        self._clients: dict[UUID, tuple[str, genai.Client]] = {}

    @property
    def model_chain(self) -> list[str]:
        """Analysis chain (the capable, pricier models): photos, satellite/layout images, expert data analysis."""
        return [self.model, *[m for m in self.fallback_models if m != self.model]]

    @property
    def chat_chain(self) -> list[str]:
        """Chat back-and-forth chain (lite models)."""
        return [self.chat_model, *[m for m in self.chat_fallback_models if m != self.chat_model]]

    def chat_generation_config(self) -> types.GenerateContentConfig:
        """Generation settings of the chat agent. Temperature is left at the model default unless configured
        (Gemini 3 is tuned for 1.0); thinking depth comes from `chat_thinking_level`."""
        kwargs: dict = {}
        if self.chat_temperature is not None:
            kwargs["temperature"] = float(self.chat_temperature)
        if self.chat_thinking_level:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(self.chat_thinking_level.upper())
            )
        return types.GenerateContentConfig(**kwargs)

    async def _generate(self, client: genai.Client, models: list[str], **kwargs):
        """generate_content over a chain of models, moving on when one is overloaded."""
        last_exc: BaseException | None = None
        for model in models:
            try:
                return await client.aio.models.generate_content(model=model, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if not _is_retryable(exc):
                    break
                logger.warning(f"Gemini model {model} unavailable ({getattr(exc, 'code', '')}); trying next")
        raise translate_provider_error(last_exc) from None

    async def api_key_for(self, user_id: UUID) -> str:
        return await self.credentials.get_api_key(user_id)

    async def client_for(self, user_id: UUID) -> genai.Client:
        api_key = await self.api_key_for(user_id)
        fingerprint = hashlib.sha256(api_key.encode()).hexdigest()
        cached = self._clients.get(user_id)
        if cached and cached[0] == fingerprint:
            return cached[1]
        client = build_client(api_key)
        self._clients[user_id] = (fingerprint, client)
        return client

    async def generate_structured(
        self,
        user_id: UUID,
        contents: Any,
        schema: Type[T],
        system_instruction: Optional[str] = None,
        model: Optional[str] = None,
        thinking_level: Optional[str] = None,
        usage_sink=None,
    ) -> T:
        """`thinking_level` (minimal | low | medium | high) caps the reasoning of a Gemini 3 model: a routing or
        extraction call has no use for deep thinking, which is billed as output."""
        client = await self.client_for(user_id)
        config_kwargs: dict = {}
        if thinking_level:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel(thinking_level.upper())
            )
        response = await self._generate(
            client,
            [model] if model else self.model_chain,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=schema,
                **config_kwargs,
            ),
        )
        if usage_sink is not None:
            usage_sink.add(response.usage_metadata)
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "{}")
        except ValidationError as exc:
            logger.error(f"Gemini returned an invalid {schema.__name__}: {exc.errors(include_input=False)}")
            raise ProviderError("La IA devolvió una respuesta con formato inválido. Reintentá en un momento.") from None

    async def generate_text(
        self, user_id: UUID, prompt: str, model: Optional[str] = None, models: Optional[list[str]] = None
    ) -> str:
        """Lite models by default (titles); pass models=model_chain for an analysis-grade answer."""
        client = await self.client_for(user_id)
        chain = models or list(dict.fromkeys([model or self.lite_model, *self.chat_chain]))
        response = await self._generate(client, chain, contents=prompt)
        return (response.text or "").strip()

    async def embed(self, user_id: UUID, texts: Sequence[str], task_type: str) -> list[list[float]]:
        client = await self.client_for(user_id)
        try:
            response = await client.aio.models.embed_content(
                model=self.embedding_model,
                contents=list(texts),
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=self.embedding_dimensions
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise translate_provider_error(exc) from None
        return [list(e.values) for e in response.embeddings]
