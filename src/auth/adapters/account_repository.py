# src/auth/adapters/account_repository.py
"""
Account repository implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from ..domain.models import Account


class AccountRepositoryInterface(ABC):
    """Interface for account repository operations."""
    
    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> Optional[Account]:
        """Get account by ID."""
        ...

    @abstractmethod
    async def create(self, name: str) -> Account:
        """Create a new account."""
        ...


class SQLAlchemyAccountRepository(AccountRepositoryInterface):
    """SQLAlchemy implementation of account repository."""
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get_by_id(self, account_id: UUID) -> Optional[Account]:
        """Get account by ID."""
        async with self.session_factory() as session:
            result = await session.execute(select(Account).filter(Account.id == account_id))
            return result.scalars().first()

    async def create(self, name: str) -> Account:
        """Create a new account."""
        db_account = Account(name=name)

        async with self.session_factory() as session:
            async with session.begin():
                session.add(db_account)
            await session.commit()
            await session.refresh(db_account)
        return db_account
