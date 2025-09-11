import sys # Keep for now, or remove if no other stderr prints
from fastapi import APIRouter, Depends, HTTPException
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.account_service import AccountService
from src.app.users.domain.schemas.user_schema import User, UserCreate
from src.app.users.service.user_service import UserService
from src.app.users.service.exceptions import UserAlreadyExistsError
from src.app.container import Container
from src.app.auth.infrastructure.auth_dependencies import get_current_user
from uuid import UUID

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=User)
@inject
async def create_user_endpoint( 
    user: UserCreate,
    user_service: UserService = Depends(Provide[Container.users.user_service]),
):
    # --- DEBUGGING REMOVED ---
    try:
        return await user_service.create_user(user_create_dto=user)
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/me", response_model=dict)
@inject
async def get_me(
    current_user: User = Depends(get_current_user),
    user_service: UserService = Depends(Provide[Container.users.user_service]),
    account_service: AccountService = Depends(Provide[Container.farm_management.account_service]),
):
    account = await account_service.get_account(current_user.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"user": current_user, "account": account}

@router.get("/{user_id}", response_model=User)
@inject
async def read_user_endpoint( 
    user_id: UUID,
    user_service: UserService = Depends(Provide[Container.users.user_service]),
):
    db_user = await user_service.get_user(user_id=user_id) 
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user 