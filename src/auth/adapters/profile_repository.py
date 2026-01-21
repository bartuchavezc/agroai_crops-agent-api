# src/auth/adapters/profile_repository.py
"""
User profile repository implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from ..domain.models import UserProfile


class ProfileRepositoryInterface(ABC):
    """Interface for user profile repository operations."""
    
    @abstractmethod
    async def get_by_id(self, profile_id: UUID) -> Optional[UserProfile]:
        """Get profile by ID."""
        ...

    @abstractmethod
    async def get_by_user_id(self, user_id: UUID) -> Optional[UserProfile]:
        """Get profile by user ID."""
        ...

    @abstractmethod
    async def create(self, user_id: UUID, form: dict, categories: dict) -> UserProfile:
        """Create a new user profile."""
        ...

    @abstractmethod
    async def update(self, profile: UserProfile, form: dict, categories: dict) -> UserProfile:
        """Update an existing user profile."""
        ...


class SQLAlchemyProfileRepository(ProfileRepositoryInterface):
    """SQLAlchemy implementation of user profile repository."""
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def get_by_id(self, profile_id: UUID) -> Optional[UserProfile]:
        """Get profile by ID."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(UserProfile).filter(UserProfile.id == profile_id)
            )
            return result.scalars().first()

    async def get_by_user_id(self, user_id: UUID) -> Optional[UserProfile]:
        """Get profile by user ID."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(UserProfile).filter(UserProfile.user_id == user_id)
            )
            return result.scalars().first()

    async def create(self, user_id: UUID, form: dict, categories: dict) -> UserProfile:
        """
        Create a new user profile.
        
        Args:
            user_id: The user's UUID
            form: The raw form data (q1-q10 answers)
            categories: Calculated categories (experience, goal, risk, philosophy, profile)
        """
        db_profile = UserProfile(
            user_id=user_id,
            form=form,
            experience=categories.get("experience"),
            goal=categories.get("goal"),
            risk=categories.get("risk"),
            philosophy=categories.get("philosophy"),
            profile=categories.get("profile")
        )

        async with self.session_factory() as session:
            async with session.begin():
                session.add(db_profile)
            await session.commit()
            await session.refresh(db_profile)
        return db_profile

    async def update(self, profile: UserProfile, form: dict, categories: dict) -> UserProfile:
        """
        Update an existing user profile.
        
        Args:
            profile: The existing profile to update
            form: The new form data
            categories: New calculated categories
        """
        async with self.session_factory() as session:
            async with session.begin():
                # Merge the detached profile into this session
                merged_profile = await session.merge(profile)
                
                # Update fields
                merged_profile.form = form
                merged_profile.experience = categories.get("experience")
                merged_profile.goal = categories.get("goal")
                merged_profile.risk = categories.get("risk")
                merged_profile.philosophy = categories.get("philosophy")
                merged_profile.profile = categories.get("profile")
            
            await session.commit()
            await session.refresh(merged_profile)
        return merged_profile
