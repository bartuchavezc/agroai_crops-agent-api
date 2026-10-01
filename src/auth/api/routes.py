"""
Authentication, account membership and onboarding routes.
"""
from typing import List
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status

from ..services.account_service import AccountService
from src.shared.utils.errors import UserAlreadyExistsError

from ..domain.models import ROLE_OWNER
from ..domain.schemas import (
    AccountRead,
    EnrollRequest,
    LoginRequest,
    MemberCreate,
    MemberRoleUpdate,
    MeResponse,
    PasswordChangeRequest,
    SignupRequest,
    TokenResponse,
    UserCreate,
    UserProfileContext,
    UserProfileRead,
    UserRead,
)
from ..services.auth_service import AuthService
from ..services.profile_service import ProfileService
from ..services.user_service import UserService
from .dependencies import get_current_user, require_owner

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse, summary="Login")
@inject
async def login(
    login_req: LoginRequest,
    auth_service: AuthService = Depends(Provide["auth.auth_service"]),
):
    user = await auth_service.authenticate_user(login_req.email, login_req.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=auth_service.create_token(user))


@router.post("/signup", response_model=TokenResponse, summary="Sign Up (new account + owner)")
@inject
async def signup(
    signup_req: SignupRequest,
    user_service: UserService = Depends(Provide["auth.user_service"]),
    auth_service: AuthService = Depends(Provide["auth.auth_service"]),
    account_service: AccountService = Depends(Provide["auth.account_service"]),
):
    if not auth_service.allow_public_signup:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public signup is disabled. Ask an account owner to add you as a member.",
        )
    if await user_service.get_user_by_email(signup_req.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered.")

    account_name = (
        signup_req.account_name
        or " ".join(p for p in (signup_req.first_name, signup_req.last_name) if p)
        or signup_req.email.split("@")[0]
    )
    account = await account_service.create_account(name=account_name)
    try:
        user = await user_service.create_user(
            user_create_dto=UserCreate(
                email=signup_req.email,
                password=signup_req.password,
                first_name=signup_req.first_name,
                last_name=signup_req.last_name,
                account_id=account.id,
                role=ROLE_OWNER,
            )
        )
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    return TokenResponse(access_token=auth_service.create_token(user))


@router.get("/me", response_model=MeResponse, summary="Get Current User")
@inject
async def get_me(
    current_user: UserRead = Depends(get_current_user),
    account_service: AccountService = Depends(Provide["auth.account_service"]),
):
    account = await account_service.get_account(current_user.account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return MeResponse(user=current_user, account=AccountRead.model_validate(account))


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT, summary="Change Own Password")
@inject
async def change_password(
    body: PasswordChangeRequest,
    current_user: UserRead = Depends(get_current_user),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    if body.new_password == body.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contraseña debe ser distinta de la actual.")
    if not await user_service.change_password(current_user.id, body.current_password, body.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contraseña actual es incorrecta.")


@router.get("/users", response_model=List[UserRead], summary="List Account Members")
@inject
async def list_members(
    current_user: UserRead = Depends(get_current_user),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    return await user_service.list_account_members(current_user.account_id)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Add Account Member")
@inject
async def add_member(
    member: MemberCreate,
    owner: UserRead = Depends(require_owner),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    try:
        user = await user_service.create_user(
            user_create_dto=UserCreate(
                email=member.email,
                password=member.password,
                first_name=member.first_name,
                last_name=member.last_name,
                account_id=owner.account_id,
                role=member.role,
            )
        )
    except UserAlreadyExistsError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from None
    return UserRead.model_validate(user)


@router.get("/users/{user_id}", response_model=UserRead, summary="Get Account Member")
@inject
async def read_member(
    user_id: UUID,
    current_user: UserRead = Depends(get_current_user),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    user = await user_service.get_user(user_id=user_id)
    if user is None or user.account_id != current_user.account_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/users/{user_id}/role", response_model=UserRead, summary="Change Member Role")
@inject
async def change_member_role(
    user_id: UUID,
    body: MemberRoleUpdate,
    owner: UserRead = Depends(require_owner),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    if user_id == owner.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The owner cannot change their own role.")
    user = await user_service.update_member_role(user_id, owner.account_id, body.role)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.post("/enroll", response_model=UserProfileRead, summary="Enroll User Profile")
@inject
async def enroll(
    enroll_req: EnrollRequest,
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"]),
):
    """Save the onboarding questionnaire (q1..q10, A/B/C) and compute the agent profile."""
    profile = await profile_service.enroll(current_user.id, enroll_req.form)
    return UserProfileRead.model_validate(profile)


@router.get("/profile", response_model=UserProfileRead, summary="Get User Profile")
@inject
async def get_profile(
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"]),
):
    profile = await profile_service.get_profile(current_user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found. Please complete enrollment first.")
    return profile


@router.get("/profile/context", response_model=UserProfileContext, summary="Get Profile Context for Agent")
@inject
async def get_profile_context(
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"]),
):
    context = await profile_service.get_profile_context(current_user.id)
    if not context:
        raise HTTPException(status_code=404, detail="Profile not found. Please complete enrollment first.")
    return context
