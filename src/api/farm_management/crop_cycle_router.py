from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from uuid import UUID
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.crop_cycle_service import CropCycleService
from src.app.farm_management.domain.schemas.crop_cycle_schema import CropCycleCreate, CropCycleRead, CropCycleUpdate
from src.app.container import Container # Import the root container
# from src.app.users.service.auth_service import get_current_active_user # Placeholder for auth

router = APIRouter(
    tags=["Farm Management - Crop Cycles"],
    # dependencies=[Depends(get_current_active_user)]
)

@router.post("/crop-cycles/", response_model=CropCycleRead, status_code=status.HTTP_201_CREATED)
@inject
async def create_crop_cycle(
    crop_cycle_in: CropCycleCreate,
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    # Service handles validation of field_id and crop_master_id existence
    # This might raise NotFoundException or ValidationException from service layer
    crop_cycle = await service.create_crop_cycle(crop_cycle_in)
    return crop_cycle

# Get crop cycles for a specific field
@router.get("/crop-cycles/", response_model=List[CropCycleRead])
@inject
async def read_all_crop_cycles(
    field_id: UUID,
    active_only: bool = Query(False, description="Filter for active crop cycles only (end_date is null)"),
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    # TODO: Authorization: Check if user can access this field's crop cycles
    crop_cycles = await service.get_all_crop_cycles(field_id, active_only)
    return crop_cycles

@router.get("/crop-cycles/{crop_cycle_id}", response_model=CropCycleRead)
@inject
async def read_crop_cycle(
    crop_cycle_id: UUID,
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    crop_cycle = await service.get_crop_cycle(crop_cycle_id)
    if crop_cycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Cycle not found")
    return crop_cycle

# Get crop cycles for a specific field
@router.get("/fields/{field_id}/crop-cycles/", response_model=List[CropCycleRead])
@inject
async def read_crop_cycles_for_field(
    field_id: UUID,
    active_only: bool = Query(False, description="Filter for active crop cycles only (end_date is null)"),
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    # TODO: Authorization: Check if user can access this field's crop cycles
    crop_cycles = await service.get_crop_cycles_by_field(field_id, active_only)
    return crop_cycles

# Get crop cycles for a specific crop master type (less common, but possible)
@router.get("/crop-masters/{crop_master_id}/crop-cycles/", response_model=List[CropCycleRead])
@inject
async def read_crop_cycles_for_crop_master(
    crop_master_id: UUID,
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    crop_cycles = await service.get_crop_cycles_by_crop_master(crop_master_id)
    return crop_cycles

@router.put("/crop-cycles/{crop_cycle_id}", response_model=CropCycleRead)
@inject
async def update_crop_cycle(
    crop_cycle_id: UUID,
    crop_cycle_in: CropCycleUpdate,
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    # Service may raise ValidationException (e.g. start_date > end_date)
    updated_crop_cycle = await service.update_crop_cycle(crop_cycle_id, crop_cycle_in)
    if updated_crop_cycle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Cycle not found for update")
    return updated_crop_cycle

@router.delete("/crop-cycles/{crop_cycle_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_crop_cycle(
    crop_cycle_id: UUID,
    service: CropCycleService = Depends(Provide[Container.farm_management.crop_cycle_service])
):
    # Service may raise ConflictException if cycle is linked to reports
    deleted = await service.delete_crop_cycle(crop_cycle_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Cycle not found or could not be deleted")
    return None 