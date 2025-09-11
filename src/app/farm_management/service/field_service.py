from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.repositories.field_repository import FieldRepositoryInterface
from src.app.farm_management.domain.schemas.field_schema import FieldCreate, FieldUpdate, FieldRead
# from src.app.common.exceptions import NotFoundException, ForbiddenException
# from src.app.farm_management.domain.repositories.account_repository import AccountRepositoryInterface # If needed for auth checks

class FieldService:
    def __init__(self, 
                 field_repository: FieldRepositoryInterface
                 # account_repository: AccountRepositoryInterface # Optional, for cross-service checks
                ):
        self._repository = field_repository
        # self._account_repository = account_repository

    async def create_field(self, field_create_dto: FieldCreate) -> FieldRead:
        # Business logic: e.g., check if account_id exists and user has permission
        # For example, if you had an account_repository:
        # account = await self._account_repository.get_by_id(field_create_dto.account_id)
        # if not account:
        #     raise NotFoundException(f"Account {field_create_dto.account_id} not found.")

        field = await self._repository.create(field_create_dto)
        return FieldRead.model_validate(field)

    async def get_field(self, field_id: UUID) -> Optional[FieldRead]:
        field = await self._repository.get_by_id(field_id)
        if not field:
            return None
        return FieldRead.model_validate(field)

    async def get_fields_by_account(self, account_id: UUID) -> List[FieldRead]:
        # Business logic: e.g., check if account exists and user has permission to view its fields
        fields = await self._repository.get_by_account_id(account_id)
        return [FieldRead.model_validate(field) for field in fields]

    async def update_field(self, field_id: UUID, field_update_dto: FieldUpdate, requesting_user_id: Optional[UUID] = None) -> Optional[FieldRead]:
        # Business logic: e.g., check ownership/permissions before update
        # field_to_update = await self._repository.get_by_id(field_id)
        # if not field_to_update:
        #     raise NotFoundException(f"Field {field_id} not found.")
        # if field_to_update.account_id != associated_account_id_of_requesting_user:
        #     raise ForbiddenException("User cannot update this field.")
        
        updated_field = await self._repository.update(field_id, field_update_dto)
        if not updated_field:
            return None
        return FieldRead.model_validate(updated_field)

    async def delete_field(self, field_id: UUID, requesting_user_id: Optional[UUID] = None) -> bool:
        # Business logic: e.g., check ownership/permissions, check for dependent crop cycles
        # Also, ensure field actually exists before attempting delete if repo doesn't indicate it.
        was_deleted = await self._repository.delete(field_id)
        return was_deleted 