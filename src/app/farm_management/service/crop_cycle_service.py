from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.repositories.crop_cycle_repository import CropCycleRepositoryInterface
from src.app.farm_management.domain.schemas.crop_cycle_schema import CropCycleCreate, CropCycleUpdate, CropCycleRead
from src.app.farm_management.domain.repositories.field_repository import FieldRepositoryInterface # For validation
from src.app.farm_management.domain.repositories.crop_master_repository import CropMasterRepositoryInterface # For validation
# from src.app.common.exceptions import NotFoundException, ValidationException

class CropCycleService:
    def __init__(self, 
                 crop_cycle_repository: CropCycleRepositoryInterface,
                 field_repository: FieldRepositoryInterface, # Injected for validation
                 crop_master_repository: CropMasterRepositoryInterface # Injected for validation
                ):
        self._repository = crop_cycle_repository
        self._field_repository = field_repository
        self._crop_master_repository = crop_master_repository

    async def create_crop_cycle(self, crop_cycle_create_dto: CropCycleCreate) -> CropCycleRead:
        # Business logic: Validate field_id and crop_master_id exist
        field = await self._field_repository.get_by_id(crop_cycle_create_dto.field_id)
        if not field:
            # raise NotFoundException(f"Field with id {crop_cycle_create_dto.field_id} not found.")
            pass # Or raise specific validation error
        
        crop_master = await self._crop_master_repository.get_by_id(crop_cycle_create_dto.crop_master_id)
        if not crop_master:
            # raise NotFoundException(f"CropMaster with id {crop_cycle_create_dto.crop_master_id} not found.")
            pass # Or raise specific validation error
        
        # Further validation: e.g., no overlapping active cycles for the same field/crop type (more complex)
        
        crop_cycle = await self._repository.create(crop_cycle_create_dto)
        return CropCycleRead.model_validate(crop_cycle)

    async def get_crop_cycle(self, crop_cycle_id: UUID) -> Optional[CropCycleRead]:
        crop_cycle = await self._repository.get_by_id(crop_cycle_id)
        if not crop_cycle:
            return None
        return CropCycleRead.model_validate(crop_cycle)

    async def get_crop_cycles_by_field(self, field_id: UUID, active_only: bool = False) -> List[CropCycleRead]:
        # Business logic: e.g., validate field_id exists
        crop_cycles = await self._repository.get_by_field_id(field_id, active_only)
        return [CropCycleRead.model_validate(cc) for cc in crop_cycles]
    
    async def get_crop_cycles_by_crop_master(self, crop_master_id: UUID) -> List[CropCycleRead]:
        crop_cycles = await self._repository.get_by_crop_master_id(crop_master_id)
        return [CropCycleRead.model_validate(cc) for cc in crop_cycles]

    async def get_all_crop_cycles(self, active_only: bool = False) -> List[CropCycleRead]:
        """
        Retrieve all crop cycles from the system.
        
        Args:
            active_only (bool): If True, only return active crop cycles (not completed or cancelled)
            
        Returns:
            List[CropCycleRead]: List of all crop cycles
        """
        crop_cycles = await self._repository.get_all(active_only)
        return [CropCycleRead.model_validate(cc) for cc in crop_cycles]

    async def update_crop_cycle(self, crop_cycle_id: UUID, crop_cycle_update_dto: CropCycleUpdate) -> Optional[CropCycleRead]:
        # Business logic: e.g., validate that a crop cycle cannot be updated in a way that violates constraints.
        # For instance, start_date should not be after end_date if both are provided.
        if crop_cycle_update_dto.start_date and crop_cycle_update_dto.end_date:
            if crop_cycle_update_dto.start_date > crop_cycle_update_dto.end_date:
                # raise ValidationException("Start date cannot be after end date.")
                pass

        updated_crop_cycle = await self._repository.update(crop_cycle_id, crop_cycle_update_dto)
        if not updated_crop_cycle:
            return None
        return CropCycleRead.model_validate(updated_crop_cycle)

    async def delete_crop_cycle(self, crop_cycle_id: UUID) -> bool:
        # Business logic: e.g., check if reports are linked to this cycle before deletion.
        # report_links = await self._report_campaign_repository.get_by_crop_cycle_id(crop_cycle_id)
        # if report_links:
        #     raise ConflictException("Cannot delete crop cycle with active report links.")
        was_deleted = await self._repository.delete(crop_cycle_id)
        return was_deleted 