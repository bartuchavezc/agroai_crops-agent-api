from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from uuid import UUID
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.field_service import FieldService
from src.app.farm_management.domain.schemas.field_schema import FieldCreate, FieldRead, FieldUpdate
from src.app.container import Container # Import the root container
# from src.app.users.service.auth_service import get_current_active_user # Placeholder for auth
# from src.app.users.domain.user_model import User as UserModel # For current user type hint

router = APIRouter(
    prefix="/fields",
    tags=["Farm Management - Fields"],
    # dependencies=[Depends(get_current_active_user)] # Router-level auth
)

@router.post("/", response_model=FieldRead, status_code=status.HTTP_201_CREATED)
@inject
async def create_field(
    field_in: FieldCreate,
    service: FieldService = Depends(Provide[Container.farm_management.field_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    # TODO: Add authorization: check if current_user can create a field for field_in.account_id
    field = await service.create_field(field_in)
    return field

@router.get("/", response_model=List[FieldRead])
@inject
async def read_fields_for_account(
    account_id: UUID = Query(..., description="Account ID to filter fields by"),
    service: FieldService = Depends(Provide[Container.farm_management.field_service]),
    # current_user: UserModel = Depends(get_current_active_user) 
):
    fields = await service.get_fields_by_account(account_id)
    return fields

@router.get("/{field_id}", response_model=FieldRead)
@inject
async def read_field(
    field_id: UUID,
    service: FieldService = Depends(Provide[Container.farm_management.field_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    # TODO: Add authorization: check if current_user can access this field (e.g., owns account or is admin)
    field = await service.get_field(field_id)
    if field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found")
    return field


@router.put("/{field_id}", response_model=FieldRead)
@inject
async def update_field(
    field_id: UUID,
    field_in: FieldUpdate,
    service: FieldService = Depends(Provide[Container.farm_management.field_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    # TODO: Add authorization: check if current_user can update this field
    updated_field = await service.update_field(field_id, field_in)
    if updated_field is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found for update")
    return updated_field

@router.delete("/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_field(
    field_id: UUID,
    service: FieldService = Depends(Provide[Container.farm_management.field_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    # TODO: Add authorization: check if current_user can delete this field
    deleted = await service.delete_field(field_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Field not found for deletion")
    return None 