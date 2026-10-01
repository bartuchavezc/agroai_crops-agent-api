# src/auth/services/user_service.py
"""
User management service.
"""
from typing import List
from uuid import UUID

from ..domain.models import User
from ..domain.schemas import UserCreate, UserRead
from ..adapters.user_repository import UserRepositoryInterface
from src.shared.utils.errors import UserAlreadyExistsError


class UserService:
    """Service for handling user operations."""
    
    def __init__(self, user_repository: UserRepositoryInterface, account_service=None):
        self.user_repository = user_repository
        self.account_service = account_service

    async def create_user(self, user_create_dto: UserCreate) -> User:
        """
        Create a new user.
        
        Args:
            user_create_dto: User creation data
            
        Returns:
            Created user object
            
        Raises:
            UserAlreadyExistsError: If user with email already exists
        """
        existing_user = await self.user_repository.get_by_email(user_create_dto.email)
        if existing_user:
            raise UserAlreadyExistsError(f"User with email {user_create_dto.email} already exists.")
        return await self.user_repository.create(user_create_dto)

    async def get_user(self, user_id: UUID) -> UserRead | None:
        """
        Get a user by ID.
        
        Args:
            user_id: User's UUID
            
        Returns:
            User read schema if found, None otherwise
        """
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            return None
        return UserRead.model_validate(user)

    async def get_user_by_email(self, email: str) -> User | None:
        """
        Get a user by email.
        
        Args:
            email: User's email
            
        Returns:
            User object if found, None otherwise
        """
        return await self.user_repository.get_by_email(email)

    async def list_account_members(self, account_id: UUID) -> List[UserRead]:
        users = await self.user_repository.list_by_account(account_id)
        return [UserRead.model_validate(u) for u in users]

    async def update_member_role(self, user_id: UUID, account_id: UUID, role: str) -> UserRead | None:
        user = await self.user_repository.update_role(user_id, account_id, role)
        return UserRead.model_validate(user) if user else None

    async def change_password(self, user_id: UUID, current_password: str, new_password: str) -> bool:
        """Change a user's password after verifying the current one. False if the current one is wrong."""
        user = await self.user_repository.get_by_id(user_id)
        if not user or not User.verify_password(current_password, user.password_hash):
            return False
        await self.user_repository.update_password(user_id, User.get_password_hash(new_password))
        return True

    async def get_user_with_account(self, user_id: UUID) -> tuple[User | None, dict | None]:
        """
        Get a user with their associated account.
        
        Args:
            user_id: User's UUID
            
        Returns:
            Tuple of (user, account) or (None, None) if not found
        """
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            return None, None
        
        account = None
        if self.account_service:
            account = await self.account_service.get_account(user.account_id)
        
        return user, account
