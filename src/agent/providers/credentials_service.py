import time
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from src.shared.utils.errors import ProviderKeyMissingError
from src.shared.utils.logger import register_secret

from .encryption import SecretBox
from .gemini import PROVIDER_GEMINI, validate_gemini_key
from .repository import ProviderCredentialRepository

_KEY_CACHE_TTL_SECONDS = 60


class CredentialStatus(BaseModel):
    provider: str
    configured: bool
    key_last4: Optional[str] = None
    last_validated_at: Optional[datetime] = None


class CredentialsService:
    def __init__(self, repository: ProviderCredentialRepository, secret_box: SecretBox):
        self.repo = repository
        self.box = secret_box
        self._cache: dict[UUID, tuple[float, str]] = {}

    async def set_gemini_key(self, user_id: UUID, api_key: str) -> CredentialStatus:
        api_key = api_key.strip()
        register_secret(api_key)
        await validate_gemini_key(api_key)
        await self.repo.upsert(user_id, PROVIDER_GEMINI, self.box.encrypt(api_key), api_key[-4:])
        self._cache.pop(user_id, None)
        return await self.status(user_id)

    async def delete_gemini_key(self, user_id: UUID) -> bool:
        self._cache.pop(user_id, None)
        return await self.repo.delete(user_id, PROVIDER_GEMINI)

    async def status(self, user_id: UUID) -> CredentialStatus:
        cred = await self.repo.get(user_id, PROVIDER_GEMINI)
        if cred is None:
            return CredentialStatus(provider=PROVIDER_GEMINI, configured=False)
        return CredentialStatus(
            provider=PROVIDER_GEMINI,
            configured=True,
            key_last4=cred.key_last4,
            last_validated_at=cred.last_validated_at,
        )

    async def has_key(self, user_id: UUID) -> bool:
        return (await self.repo.get(user_id, PROVIDER_GEMINI)) is not None

    async def get_api_key(self, user_id: UUID) -> str:
        cached = self._cache.get(user_id)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        cred = await self.repo.get(user_id, PROVIDER_GEMINI)
        if cred is None:
            raise ProviderKeyMissingError()
        api_key = self.box.decrypt(cred.api_key_ciphertext)
        register_secret(api_key)
        self._cache[user_id] = (time.monotonic() + _KEY_CACHE_TTL_SECONDS, api_key)
        return api_key
