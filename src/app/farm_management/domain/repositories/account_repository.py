from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from src.app.farm_management.domain.account_model import AccountModel
from src.app.farm_management.domain.schemas.account_schema import AccountCreate, AccountUpdate

class AccountRepositoryInterface(ABC):
    @abstractmethod
    async def get_by_id(self, account_id: UUID) -> Optional[AccountModel]:
        pass

    @abstractmethod
    async def create(self, account_create_dto: AccountCreate) -> AccountModel:
        pass

    @abstractmethod
    async def update(self, account_id: UUID, account_update_dto: AccountUpdate) -> Optional[AccountModel]:
        pass

    @abstractmethod
    async def delete(self, account_id: UUID) -> bool:
        pass 