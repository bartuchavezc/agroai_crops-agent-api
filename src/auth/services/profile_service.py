# src/auth/services/profile_service.py
"""
User profile service for onboarding and enrollment.
"""
from typing import Optional
from uuid import UUID

from ..domain.models import UserProfile
from ..domain.schemas import UserProfileRead, UserProfileContext
from ..adapters.profile_repository import ProfileRepositoryInterface
from ..adapters.user_repository import UserRepositoryInterface
from .profile_calculator import ProfileCalculator


class ProfileService:
    """Service for handling user profile operations."""
    
    def __init__(
        self,
        profile_repository: ProfileRepositoryInterface,
        user_repository: UserRepositoryInterface
    ):
        self.profile_repository = profile_repository
        self.user_repository = user_repository
        self.calculator = ProfileCalculator()

    async def enroll(self, user_id: UUID, form: dict) -> UserProfile:
        """
        Create or update user profile based on onboarding form.
        Also marks the user as enrolled after successful save.
        
        Args:
            user_id: The user's UUID
            form: Dictionary with q1-q10 answers (A/B/C)
            
        Returns:
            Created or updated UserProfile
        """
        # Calculate all categories from form
        categories = self.calculator.calculate_all(form)
        
        # Check if profile already exists
        existing_profile = await self.profile_repository.get_by_user_id(user_id)
        
        if existing_profile:
            # Update existing profile
            profile = await self.profile_repository.update(
                existing_profile, form, categories
            )
        else:
            # Create new profile
            profile = await self.profile_repository.create(
                user_id, form, categories
            )
        
        # Mark user as enrolled
        await self.user_repository.mark_as_enrolled(user_id)
        
        return profile

    async def get_profile(self, user_id: UUID) -> Optional[UserProfileRead]:
        """
        Get user profile by user ID.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            UserProfileRead if found, None otherwise
        """
        profile = await self.profile_repository.get_by_user_id(user_id)
        if not profile:
            return None
        return UserProfileRead.model_validate(profile)

    async def get_profile_context(self, user_id: UUID) -> Optional[UserProfileContext]:
        """
        Get the agent context configuration for a user.
        
        This returns the configuration that should be used to customize
        the agent's behavior based on the user's psychological profile.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            UserProfileContext with calculated_profile and config, or None if no profile
        """
        profile = await self.profile_repository.get_by_user_id(user_id)
        if not profile:
            return None
        
        # Build categories dict from profile
        categories = {
            "experience": profile.experience,
            "goal": profile.goal,
            "risk": profile.risk,
            "philosophy": profile.philosophy
        }
        
        # Get agent configuration based on profile
        config = self.calculator.get_agent_config(profile.profile, categories)
        
        return UserProfileContext(
            calculated_profile=profile.profile,
            config=config
        )

    async def has_profile(self, user_id: UUID) -> bool:
        """
        Check if a user has completed onboarding.
        
        Args:
            user_id: The user's UUID
            
        Returns:
            True if user has a profile, False otherwise
        """
        profile = await self.profile_repository.get_by_user_id(user_id)
        return profile is not None
