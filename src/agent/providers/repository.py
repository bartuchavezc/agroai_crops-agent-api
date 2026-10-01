from typing import Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.base import utcnow

from .models import ProviderCredential


class ProviderCredentialRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get(self, user_id: UUID, provider: str) -> Optional[ProviderCredential]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(ProviderCredential).where(
                        ProviderCredential.user_id == user_id, ProviderCredential.provider == provider
                    )
                )
            ).scalar_one_or_none()

    async def upsert(self, user_id: UUID, provider: str, ciphertext: bytes, last4: str) -> None:
        now = utcnow()
        stmt = insert(ProviderCredential).values(
            user_id=user_id,
            provider=provider,
            api_key_ciphertext=ciphertext,
            key_last4=last4,
            last_validated_at=now,
            created_at=now,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_provider_credentials_user_provider",
            set_={
                "api_key_ciphertext": stmt.excluded.api_key_ciphertext,
                "key_last4": stmt.excluded.key_last4,
                "last_validated_at": now,
                "updated_at": now,
            },
        )
        async with self.session_factory() as session:
            await session.execute(stmt)
            await session.commit()

    async def update_ciphertext(self, user_id: UUID, provider: str, ciphertext: bytes) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(ProviderCredential)
                .where(ProviderCredential.user_id == user_id, ProviderCredential.provider == provider)
                .values(api_key_ciphertext=ciphertext)
            )
            await session.commit()

    async def delete(self, user_id: UUID, provider: str) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                delete(ProviderCredential).where(
                    ProviderCredential.user_id == user_id, ProviderCredential.provider == provider
                )
            )
            await session.commit()
        return result.rowcount > 0
