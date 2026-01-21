# src/auth/adapters/user_repository.py
"""
User repository implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from ..domain.models import User
from ..domain.schemas import UserCreate


class UserRepositoryInterface(ABC):
    """Interface for user repository operations."""
    
    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        ...

    @abstractmethod
    async def create(self, user_create_dto: UserCreate) -> User:
        """Create a new user."""
        ...

    @abstractmethod
    async def mark_as_enrolled(self, user_id: UUID) -> Optional[User]:
        """Mark a user as enrolled after completing onboarding."""
        ...


class SQLAlchemyUserRepository(UserRepositoryInterface):
    """SQLAlchemy implementation of user repository."""
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID."""
        async with self.session_factory() as session:
            result = await session.execute(select(User).filter(User.id == user_id))
            return result.scalars().first()

    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        async with self.session_factory() as session:
            result = await session.execute(select(User).filter(User.email == email))
            return result.scalars().first()

    async def create(self, user_create_dto: UserCreate) -> User:
        """Create a new user with hashed password."""
        # Convert DTO to dict and exclude password
        user_data = user_create_dto.model_dump(exclude={'password'})
        
        # Hash the password and add it as password_hash
        user_data['password_hash'] = User.get_password_hash(user_create_dto.password)
        
        # Create the user model
        db_user = User(**user_data)

        async with self.session_factory() as session:
            async with session.begin():
                session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
        return db_user

    async def mark_as_enrolled(self, user_id: UUID) -> Optional[User]:
        """Mark a user as enrolled after completing onboarding."""
        async with self.session_factory() as session:
            result = await session.execute(select(User).filter(User.id == user_id))
            user = result.scalars().first()
            
            if not user:
                return None
            
            user.is_enrolled = True
            await session.commit()
            await session.refresh(user)
        return user
