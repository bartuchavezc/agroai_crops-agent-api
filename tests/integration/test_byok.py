"""BYOK: per-user Gemini key, encrypted at rest, never returned, required for LLM endpoints."""
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

FAKE_KEY = "AIzaSyTESTKEY-0123456789abcdefghijKLMN"


async def test_chat_without_key_returns_409(client, signup):
    user = await signup("nokey")
    response = await client.post("/api/v1/chat", headers=user["headers"], json={"message": "hola"})
    assert response.status_code == 409
    assert response.json()["error_code"] == "PROVIDER_KEY_MISSING"


async def test_key_is_validated_encrypted_and_never_returned(client, signup, container):
    user = await signup("byok")
    h = user["headers"]
    assert (await client.get("/api/v1/me/provider-credentials/gemini", headers=h)).json()["configured"] is False

    with patch("src.agent.providers.credentials_service.validate_gemini_key", AsyncMock()) as validate:
        saved = await client.put("/api/v1/me/provider-credentials/gemini", headers=h, json={"api_key": FAKE_KEY})
    assert saved.status_code == 200, saved.text
    validate.assert_awaited_once_with(FAKE_KEY)
    body = saved.json()
    assert body == {**body, "configured": True, "key_last4": FAKE_KEY[-4:]}
    assert FAKE_KEY not in saved.text

    async with container.db_session_factory()() as session:
        stored = (
            await session.execute(
                text("SELECT api_key_ciphertext FROM provider_credentials WHERE user_id = :u"),
                {"u": user["user"]["id"]},
            )
        ).scalar_one()
    assert FAKE_KEY.encode() not in bytes(stored)
    assert await container.agent.credentials_service().get_api_key(user["user"]["id"]) == FAKE_KEY

    assert (await client.delete("/api/v1/me/provider-credentials/gemini", headers=h)).status_code == 204
    assert (await client.get("/api/v1/me/provider-credentials/gemini", headers=h)).json()["configured"] is False


async def test_invalid_key_is_rejected(client, signup):
    from src.shared.utils.errors import ProviderKeyInvalidError

    user = await signup("badkey")
    with patch(
        "src.agent.providers.credentials_service.validate_gemini_key",
        AsyncMock(side_effect=ProviderKeyInvalidError()),
    ):
        response = await client.put(
            "/api/v1/me/provider-credentials/gemini", headers=user["headers"], json={"api_key": FAKE_KEY}
        )
    assert response.status_code == 409
    assert response.json()["error_code"] == "PROVIDER_KEY_INVALID"


def test_logs_redact_api_keys():
    from src.shared.utils.logger import redact

    assert FAKE_KEY not in redact(f"calling gemini with key={FAKE_KEY}")


def test_logs_redact_registered_keys_of_any_format():
    from src.shared.utils.logger import redact, register_secret

    new_format_key = "AQ.Ab8RN6Kx-some-new-format-key-0123456789"
    register_secret(new_format_key)
    assert new_format_key not in redact(f"request failed for key {new_format_key}")
