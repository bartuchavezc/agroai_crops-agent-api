from abc import ABC, abstractmethod
from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.crop_master_model import CropMasterModel
from src.app.farm_management.domain.schemas.crop_master_schema import CropMasterCreate, CropMasterUpdate

class CropMasterRepositoryInterface(ABC):
    @abstractmethod
    async def get_by_id(self, crop_master_id: UUID) -> Optional[CropMasterModel]:
        pass

    @abstractmethod
    async def get_by_name(self, name: str) -> Optional[CropMasterModel]: # Useful for uniqueness
        pass

    @abstractmethod
    async def get_all(self, skip: int = 0, limit: int = 100) -> List[CropMasterModel]:
        pass

    @abstractmethod
    async def create(self, crop_master_create_dto: CropMasterCreate) -> CropMasterModel:
        pass

    @abstractmethod
    async def update(self, crop_master_id: UUID, crop_master_update_dto: CropMasterUpdate) -> Optional[CropMasterModel]:
        pass

    @abstractmethod
    async def delete(self, crop_master_id: UUID) -> bool:
        pass 