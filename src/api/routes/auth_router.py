from fastapi import APIRouter, Depends, HTTPException
from dependency_injector.wiring import inject, Provide
from src.app.auth.domain.schemas.auth_schema import LoginRequest, TokenResponse
from src.app.auth.service.auth_service import AuthService
from src.app.users.service.user_service import UserService
from src.app.users.domain.schemas.user_schema import UserCreate
from src.app.container import Container

# Rename router to auth_router for clarity
auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/login", response_model=TokenResponse)
@inject
async def login(
    login_req: LoginRequest,
    auth_service: AuthService = Depends(Provide[Container.auth.auth_service])
):
    user = await auth_service.authenticate_user(login_req.email, login_req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = auth_service.create_token(user)
    return TokenResponse(access_token=token)

@auth_router.post("/signup", response_model=TokenResponse)
@inject
async def signup(
    user_create: UserCreate,
    user_service: UserService = Depends(Provide[Container.users.user_service]),
    auth_service: AuthService = Depends(Provide[Container.auth.auth_service])
):
    user = await user_service.create_user(user_create_dto=user_create)
    token = auth_service.create_token(user)
    return TokenResponse(access_token=token) 