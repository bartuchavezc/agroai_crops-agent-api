from abc import ABC, abstractmethod
from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.field_model import FieldModel
from src.app.farm_management.domain.schemas.field_schema import FieldCreate, FieldUpdate

class FieldRepositoryInterface(ABC):
    @abstractmethod
    async def get_by_id(self, field_id: UUID) -> Optional[FieldModel]:
        pass

    @abstractmethod
    async def get_by_account_id(self, account_id: UUID) -> List[FieldModel]:
        pass

    @abstractmethod
    async def create(self, field_create_dto: FieldCreate) -> FieldModel:
        pass

    @abstractmethod
    async def update(self, field_id: UUID, field_update_dto: FieldUpdate) -> Optional[FieldModel]:
        pass

    @abstractmethod
    async def delete(self, field_id: UUID) -> bool:
        pass 