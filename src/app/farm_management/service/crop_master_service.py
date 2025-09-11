from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.repositories.crop_master_repository import CropMasterRepositoryInterface
from src.app.farm_management.domain.schemas.crop_master_schema import CropMasterCreate, CropMasterUpdate, CropMasterRead
# from src.app.common.exceptions import NotFoundException, ConflictException

class CropMasterService:
    def __init__(self, crop_master_repository: CropMasterRepositoryInterface):
        self._repository = crop_master_repository

    async def create_crop_master(self, crop_master_create_dto: CropMasterCreate) -> CropMasterRead:
        # Business logic: e.g., check for name uniqueness before creation
        existing = await self._repository.get_by_name(crop_master_create_dto.name)
        if existing:
            # raise ConflictException(f"CropMaster with name '{crop_master_create_dto.name}' already exists.")
            # For now, let's return the existing one or raise a generic error, depending on desired behavior
            # This behavior (returning existing or erroring) should be consistent.
            # Consider if this check should be in repo or service. Usually service for user-facing errors.
            pass # Pass for now, allowing repository's potential DB error to propagate if name is unique constraint

        crop_master = await self._repository.create(crop_master_create_dto)
        return CropMasterRead.model_validate(crop_master)

    async def get_crop_master(self, crop_master_id: UUID) -> Optional[CropMasterRead]:
        crop_master = await self._repository.get_by_id(crop_master_id)
        if not crop_master:
            return None
        return CropMasterRead.model_validate(crop_master)
    
    async def get_crop_master_by_name(self, name: str) -> Optional[CropMasterRead]:
        crop_master = await self._repository.get_by_name(name)
        if not crop_master:
            return None
        return CropMasterRead.model_validate(crop_master)

    async def get_all_crop_masters(self, skip: int = 0, limit: int = 100) -> List[CropMasterRead]:
        crop_masters = await self._repository.get_all(skip=skip, limit=limit)
        return [CropMasterRead.model_validate(cm) for cm in crop_masters]

    async def update_crop_master(self, crop_master_id: UUID, crop_master_update_dto: CropMasterUpdate) -> Optional[CropMasterRead]:
        if crop_master_update_dto.name is not None:
            existing_by_name = await self._repository.get_by_name(crop_master_update_dto.name)
            if existing_by_name and existing_by_name.id != crop_master_id:
                # raise ConflictException(f"Another CropMaster with name '{crop_master_update_dto.name}' already exists.")
                pass # Let DB handle for now or raise a specific error
        
        updated_crop_master = await self._repository.update(crop_master_id, crop_master_update_dto)
        if not updated_crop_master:
            return None
        return CropMasterRead.model_validate(updated_crop_master)

    async def delete_crop_master(self, crop_master_id: UUID) -> bool:
        # Business logic: e.g., check if this crop master is used by any CropCycles before deletion
        # crop_cycles_using_this = await self._crop_cycle_repository.get_by_crop_master_id(crop_master_id)
        # if crop_cycles_using_this:
        #     raise ConflictException("Cannot delete CropMaster as it is currently in use by crop cycles.")
        was_deleted = await self._repository.delete(crop_master_id)
        return was_deleted 