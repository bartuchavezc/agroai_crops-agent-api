from abc import ABC, abstractmethod
from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.crop_cycle_model import CropCycleModel
from src.app.farm_management.domain.schemas.crop_cycle_schema import CropCycleCreate, CropCycleUpdate

class CropCycleRepositoryInterface(ABC):
    @abstractmethod
    async def get_by_id(self, crop_cycle_id: UUID) -> Optional[CropCycleModel]:
        pass

    @abstractmethod
    async def get_by_field_id(self, field_id: UUID, active_only: bool = False) -> List[CropCycleModel]: # Get all cycles for a field
        pass

    @abstractmethod
    async def get_by_crop_master_id(self, crop_master_id: UUID) -> List[CropCycleModel]: # Get all cycles for a crop type
        pass

    @abstractmethod
    async def get_all(self, active_only: bool = False) -> List[CropCycleModel]:
        """
        Retrieve all crop cycles from the database.
        
        Args:
            active_only (bool): If True, only return active crop cycles (not completed or cancelled)
            
        Returns:
            List[CropCycleModel]: List of all crop cycles
        """
        pass

    @abstractmethod
    async def create(self, crop_cycle_create_dto: CropCycleCreate) -> CropCycleModel:
        pass

    @abstractmethod
    async def update(self, crop_cycle_id: UUID, crop_cycle_update_dto: CropCycleUpdate) -> Optional[CropCycleModel]:
        pass

    @abstractmethod
    async def delete(self, crop_cycle_id: UUID) -> bool:
        pass 