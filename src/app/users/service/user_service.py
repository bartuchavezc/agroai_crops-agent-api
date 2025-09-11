from ..domain.user_model import User as UserModel
from src.app.users.domain.schemas.user_schema import UserCreate, User as UserRead
from ..domain.user_repository import UserRepositoryInterface
from .exceptions import UserAlreadyExistsError
from src.app.farm_management.service.account_service import AccountService
from uuid import UUID


class UserService:
    def __init__(self, user_repository: UserRepositoryInterface, account_service: AccountService = None):
        self.user_repository = user_repository
        self.account_service = account_service

    async def create_user(self, user_create_dto: UserCreate) -> UserModel:
        existing_user = await self.user_repository.get_by_email(user_create_dto.email)
        if existing_user:
            raise UserAlreadyExistsError(f"User with email {user_create_dto.email} already exists.")
        # Password hashing is part of the repository's create method now
        return await self.user_repository.create(user_create_dto)

    async def get_user(self, user_id: UUID) -> UserModel | None:
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            return None
        return UserRead.model_validate(user) 

    async def get_user_by_email(self, email: str) -> UserModel | None:
        return await self.user_repository.get_by_email(email)

    async def get_user_with_account(self, user_id: UUID) -> tuple[UserModel | None, dict | None]:
        user = await self.user_repository.get_by_id(user_id)
        if not user:
            return None, None
        
        account = None
        if self.account_service:
            account = await self.account_service.get_account(user.account_id)
        
        return user, account 