from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from uuid import UUID
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.crop_master_service import CropMasterService
from src.app.farm_management.domain.schemas.crop_master_schema import CropMasterCreate, CropMasterRead, CropMasterUpdate
from src.app.container import Container # Import the root container
# from src.app.users.service.auth_service import get_current_active_user # Placeholder for auth

router = APIRouter(
    tags=["Farm Management - Crop Masters"],
    # dependencies=[Depends(get_current_active_user)]
)

@router.post("/crop-masters/", response_model=CropMasterRead, status_code=status.HTTP_201_CREATED)
@inject
async def create_crop_master(
    crop_master_in: CropMasterCreate,
    service: CropMasterService = Depends(Provide[Container.farm_management.crop_master_service])
):
    # Service handles uniqueness check for name, might raise ConflictException
    # Consider how to map service exceptions to HTTP exceptions here or in a middleware
    crop_master = await service.create_crop_master(crop_master_in)
    return crop_master

@router.get("/crop-masters/", response_model=List[CropMasterRead])
@inject
async def read_all_crop_masters(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    service: CropMasterService = Depends(Provide[Container.farm_management.crop_master_service])
):
    crop_masters = await service.get_all_crop_masters(skip=skip, limit=limit)
    return crop_masters

@router.get("/crop-masters/{crop_master_id}", response_model=CropMasterRead)
@inject
async def read_crop_master(
    crop_master_id: UUID,
    service: CropMasterService = Depends(Provide[Container.farm_management.crop_master_service])
):
    crop_master = await service.get_crop_master(crop_master_id)
    if crop_master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Master not found")
    return crop_master

@router.put("/crop-masters/{crop_master_id}", response_model=CropMasterRead)
@inject
async def update_crop_master(
    crop_master_id: UUID,
    crop_master_in: CropMasterUpdate,
    service: CropMasterService = Depends(Provide[Container.farm_management.crop_master_service])
):
    # Service handles uniqueness check for name on update, might raise ConflictException
    updated_crop_master = await service.update_crop_master(crop_master_id, crop_master_in)
    if updated_crop_master is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Master not found for update")
    return updated_crop_master

@router.delete("/crop-masters/{crop_master_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_crop_master(
    crop_master_id: UUID,
    service: CropMasterService = Depends(Provide[Container.farm_management.crop_master_service])
):
    # Service might raise ConflictException if crop master is in use
    deleted = await service.delete_crop_master(crop_master_id)
    if not deleted:
        # This case might be hit if not found, or if service returns False for other reasons (e.g. in use but no exception)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crop Master not found or could not be deleted")
    return None 