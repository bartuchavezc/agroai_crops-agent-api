from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.account_service import AccountService
from src.app.farm_management.domain.schemas.account_schema import AccountCreate, AccountRead, AccountUpdate
from src.app.container import Container # Import the root container
# from src.app.users.service.auth_service import get_current_active_user # Placeholder for auth
# from src.app.users.domain.user_model import User as UserModel # For current user type hint

router = APIRouter(
    # prefix="/accounts", # Prefix will be part of a parent router for /farm_management
    tags=["Farm Management - Accounts"],
    # dependencies=[Depends(get_current_active_user)] # Optional: router-level auth
)

@router.post("/accounts/", response_model=AccountRead, status_code=status.HTTP_201_CREATED) # Full path from /farm_management
@inject
async def create_account(
    account_in: AccountCreate,
    service: AccountService = Depends(Provide[Container.farm_management.account_service]),
    # current_user: UserModel = Depends(get_current_active_user) # Optional: endpoint-level auth/user context
):
    account = await service.create_account(account_in)
    return account

@router.get("/accounts/{account_id}", response_model=AccountRead)
@inject
async def read_account(
    account_id: UUID,
    service: AccountService = Depends(Provide[Container.farm_management.account_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    account = await service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account

@router.put("/accounts/{account_id}", response_model=AccountRead)
@inject
async def update_account(
    account_id: UUID,
    account_in: AccountUpdate,
    service: AccountService = Depends(Provide[Container.farm_management.account_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    updated_account = await service.update_account(account_id, account_in)
    if updated_account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found for update")
    return updated_account

@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_account(
    account_id: UUID,
    service: AccountService = Depends(Provide[Container.farm_management.account_service]),
    # current_user: UserModel = Depends(get_current_active_user)
):
    deleted = await service.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found for deletion")
    return None 