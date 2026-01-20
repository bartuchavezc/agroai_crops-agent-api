# src/auth/api/routes.py
"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide
from uuid import UUID

from ..domain.schemas import LoginRequest, TokenResponse, UserCreate, UserRead
from ..services.auth_service import AuthService
from ..services.user_service import UserService
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse, summary="Login")
@inject
async def login(
    login_req: LoginRequest,
    auth_service: AuthService = Depends(Provide["auth.auth_service"])
):
    """
    Authenticate user and return access token.
    """
    user = await auth_service.authenticate_user(login_req.email, login_req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_service.create_token(user)
    return TokenResponse(access_token=token)


@router.post("/signup", response_model=TokenResponse, summary="Sign Up")
@inject
async def signup(
    user_create: UserCreate,
    user_service: UserService = Depends(Provide["auth.user_service"]),
    auth_service: AuthService = Depends(Provide["auth.auth_service"])
):
    """
    Create a new user and return access token.
    """
    from src.shared.utils.errors import UserAlreadyExistsError
    
    try:
        user = await user_service.create_user(user_create_dto=user_create)
        token = auth_service.create_token(user)
        return TokenResponse(access_token=token)
    except UserAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/users", response_model=UserRead, summary="Create User")
@inject
async def create_user_endpoint(
    user: UserCreate,
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    """
    Create a new user (admin endpoint).
    """
    from src.shared.utils.errors import UserAlreadyExistsError
    
    try:
        return await user_service.create_user(user_create_dto=user)
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/me", response_model=dict, summary="Get Current User")
@inject
async def get_me(
    current_user: UserRead = Depends(get_current_user),
    account_service = Depends(Provide["shared.account_service"]),
):
    """
    Get current authenticated user with account info.
    """
    account = await account_service.get_account(current_user.account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return {"user": current_user, "account": account}


@router.get("/users/{user_id}", response_model=UserRead, summary="Get User by ID")
@inject
async def read_user_endpoint(
    user_id: UUID,
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    """
    Get a user by their ID.
    """
    db_user = await user_service.get_user(user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return db_user
