from typing import Optional
from uuid import UUID

from src.app.farm_management.domain.repositories.account_repository import AccountRepositoryInterface
from src.app.farm_management.domain.schemas.account_schema import AccountCreate, AccountUpdate, AccountRead
# Assuming an exception for not found, or handle directly in service
# from src.app.common.exceptions import NotFoundException 

class AccountService:
    def __init__(self, account_repository: AccountRepositoryInterface):
        self._repository = account_repository

    async def create_account(self, account_create_dto: AccountCreate) -> AccountRead:
        # Business logic before creation (e.g., validation, checks) can go here
        account = await self._repository.create(account_create_dto)
        return AccountRead.model_validate(account) # Pydantic v2
        # return AccountRead.from_orm(account) # Pydantic v1

    async def get_account(self, account_id: UUID) -> Optional[AccountRead]:
        account = await self._repository.get_by_id(account_id)
        if not account:
            # raise NotFoundException(detail=f"Account with id {account_id} not found")
            return None
        return AccountRead.model_validate(account)

    async def update_account(self, account_id: UUID, account_update_dto: AccountUpdate) -> Optional[AccountRead]:
        # Ensure account exists before update if repository doesn't handle it
        # Or rely on repository returning None if not found after update attempt
        updated_account = await self._repository.update(account_id, account_update_dto)
        if not updated_account:
            # raise NotFoundException(detail=f"Account with id {account_id} not found for update")
            return None
        return AccountRead.model_validate(updated_account)

    async def delete_account(self, account_id: UUID) -> bool:
        # Business logic before deletion (e.g., check for dependent entities)
        was_deleted = await self._repository.delete(account_id)
        # if not was_deleted:
            # raise NotFoundException(detail=f"Account with id {account_id} not found for deletion")
        return was_deleted 