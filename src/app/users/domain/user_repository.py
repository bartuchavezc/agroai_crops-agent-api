from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from .user_model import User as UserModel
from .schemas.user_schema import UserCreate

class UserRepositoryInterface(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> Optional[UserModel]:
        pass

    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[UserModel]:
        pass

    @abstractmethod
    async def create(self, user_create_dto: UserCreate) -> UserModel:
        pass 