import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from google.genai import errors as genai_errors

from src.agent.providers import gemini
from src.agent.providers.gemini import GeminiGateway, backoff_delay, patient_calls, quota_info
from src.shared.utils.errors import ProviderQuotaExceededError


def _quota_error(quota_id: str | None, retry_delay: str | None = None) -> genai_errors.APIError:
    details = []
    if quota_id:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]})
    if retry_delay:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay})
    return genai_errors.APIError(
        429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "quota", "details": details}}
    )


PER_MINUTE = "GenerateContentInputTokensPerModelPerMinute-FreeTier"
PER_DAY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


def test_quota_info_reads_which_quota_ran_out_and_the_suggested_delay():
    assert quota_info(_quota_error(PER_MINUTE, "37s")) == ("minute", 37.0)
    assert quota_info(_quota_error(PER_DAY, "12.5s")) == ("day", 12.5)
    assert quota_info(_quota_error(None)) == (None, None)  # a bare 429
    assert quota_info(genai_errors.APIError(503, {"error": {"code": 503}})) == (None, None)
    assert quota_info(RuntimeError("boom")) == (None, None)


def test_backoff_uses_the_suggested_delay_else_doubles_and_never_passes_a_minute():
    assert 37 <= backoff_delay(0, 37.0) <= 37 * 1.2
    assert 5 <= backoff_delay(0, None) <= 6 and 10 <= backoff_delay(1, None) <= 12
    assert backoff_delay(6, None) == 60 and backoff_delay(0, 300.0) == 60


def _gateway_with(responses: list) -> tuple[GeminiGateway, AsyncMock]:
    gateway = GeminiGateway(
        credentials_service=None,
        config={"model": "m1", "fallback_models": ["m2"], "lite_model": "l", "embedding_model": "e",
                "embedding_dimensions": 768},
    )
    call = AsyncMock(side_effect=responses)
    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=call)))
    return gateway, client, call


def _ok():
    return SimpleNamespace(usage_metadata=None, text="ok")


def _models(call):
    return [c.kwargs["model"] for c in call.call_args_list]


async def test_a_background_job_waits_out_a_per_minute_quota_on_the_same_model():
    gateway, client, call = _gateway_with([_quota_error(PER_MINUTE, "20s"), _ok()])
    with patch.object(gemini.asyncio, "sleep", AsyncMock()) as sleep, patient_calls():
        assert (await gateway._generate(client, gateway.model_chain, contents="x")).text == "ok"
    assert _models(call) == ["m1", "m1"]
    assert 20 <= sleep.await_args.args[0] <= 24


async def test_a_per_day_quota_moves_to_the_next_model_without_waiting():
    gateway, client, call = _gateway_with([_quota_error(PER_DAY, "20s"), _ok()])
    with patch.object(gemini.asyncio, "sleep", AsyncMock()) as sleep, patient_calls():
        await gateway._generate(client, gateway.model_chain, contents="x")
    assert _models(call) == ["m1", "m2"] and sleep.await_count == 0


async def test_an_interactive_call_never_waits():
    gateway, client, call = _gateway_with([_quota_error(PER_MINUTE, "20s"), _ok()])
    with patch.object(gemini.asyncio, "sleep", AsyncMock()) as sleep:
        await gateway._generate(client, gateway.model_chain, contents="x")
    assert _models(call) == ["m1", "m2"] and sleep.await_count == 0


async def test_waits_are_bounded_then_the_chain_moves_on_and_finally_gives_up():
    errors = [_quota_error(PER_MINUTE)] * (2 * (gemini.QUOTA_RETRIES + 1))
    gateway, client, call = _gateway_with(errors)
    with patch.object(gemini.asyncio, "sleep", AsyncMock()) as sleep, patient_calls():
        with pytest.raises(ProviderQuotaExceededError):
            await gateway._generate(client, gateway.model_chain, contents="x")
    assert _models(call) == ["m1"] * 4 + ["m2"] * 4
    assert [round(c.args[0]) // 5 for c in sleep.await_args_list[:3]] == [1, 2, 4]  # 5s, 10s, 20s (+ jitter)


async def test_patience_is_scoped_to_the_job():
    with patient_calls():
        assert gemini._PATIENT.get() is True
    assert gemini._PATIENT.get() is False


async def test_background_analyses_on_the_same_key_run_one_at_a_time():
    keys = {}
    credentials = SimpleNamespace(get_api_key=AsyncMock(side_effect=lambda user_id: keys[user_id]))
    gateway = GeminiGateway(
        credentials_service=credentials,
        config={"model": "m", "lite_model": "l", "embedding_model": "e", "embedding_dimensions": 768},
    )
    owner, member, other = uuid4(), uuid4(), uuid4()
    keys.update({owner: "shared-key", member: "shared-key", other: "own-key"})
    running: set[str] = set()
    seen_together: list[set[str]] = []

    async def job(user_id, name):
        async with gateway.serialized(user_id):
            running.add(name)
            await asyncio.sleep(0.01)
            seen_together.append(set(running))
            running.discard(name)

    await asyncio.gather(job(owner, "a"), job(member, "b"), job(other, "c"))
    assert not any({"a", "b"} <= together for together in seen_together)  # same key: one after the other
    assert any("c" in together and len(together) > 1 for together in seen_together)  # its own key: alongside
