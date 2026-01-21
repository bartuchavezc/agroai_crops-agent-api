# src/auth/api/routes.py
"""
Authentication API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide
from uuid import UUID

from ..domain.schemas import (
    LoginRequest, TokenResponse, UserCreate, UserRead, SignupRequest,
    EnrollRequest, UserProfileRead, UserProfileContext
)
from ..services.auth_service import AuthService
from ..services.user_service import UserService
from ..services.profile_service import ProfileService
from src.shared.services.account_service import AccountService
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
    signup_req: SignupRequest,
    user_service: UserService = Depends(Provide["auth.user_service"]),
    auth_service: AuthService = Depends(Provide["auth.auth_service"]),
    account_service: AccountService = Depends(Provide["shared.account_service"])
):
    """
    Create a new account and user, then return access token.
    The account name is derived from the user's name or email.
    """
    from src.shared.utils.errors import UserAlreadyExistsError
    
    try:
        # Generate account name from user data
        if signup_req.first_name and signup_req.last_name:
            account_name = f"{signup_req.first_name} {signup_req.last_name}"
        elif signup_req.first_name:
            account_name = signup_req.first_name
        else:
            # Use email prefix as account name
            account_name = signup_req.email.split("@")[0]
        
        # Create the account first
        account = await account_service.create_account(name=account_name)
        
        # Create the user with the new account_id
        user_create = UserCreate(
            email=signup_req.email,
            password=signup_req.password,
            first_name=signup_req.first_name,
            last_name=signup_req.last_name,
            account_id=account.id
        )
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


# ============================================
# User Profile / Enrollment Endpoints
# ============================================

@router.post("/enroll", response_model=UserProfileRead, summary="Enroll User Profile")
@inject
async def enroll(
    enroll_req: EnrollRequest,
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"])
):
    """
    Create or update user profile based on onboarding questionnaire.
    
    The form should contain q1-q10 answers (A/B/C) that determine:
    - Experience level (q1-q2)
    - Production goal (q3)
    - Risk tolerance (q4-q5)
    - Philosophy (q6-q7)
    - Tech preferences (q8-q10)
    
    Based on these answers, a profile type is calculated:
    - guardian: Novice, conservative users
    - purist: Organic philosophy with experience
    - alchemist: High risk tolerance + premium goals
    - professional: Expert with advanced tech preferences
    """
    profile = await profile_service.enroll(current_user.id, enroll_req.form)
    return UserProfileRead.model_validate(profile)


@router.get("/profile", response_model=UserProfileRead, summary="Get User Profile")
@inject
async def get_profile(
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"])
):
    """
    Get the current user's profile.
    
    Returns the complete profile including:
    - Raw form data
    - Calculated categories (experience, goal, risk, philosophy)
    - Calculated profile type
    """
    profile = await profile_service.get_profile(current_user.id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please complete enrollment first."
        )
    return profile


@router.get("/profile/context", response_model=UserProfileContext, summary="Get Profile Context for Agent")
@inject
async def get_profile_context(
    current_user: UserRead = Depends(get_current_user),
    profile_service: ProfileService = Depends(Provide["auth.profile_service"])
):
    """
    Get the agent context configuration based on user profile.
    
    This endpoint returns the configuration that should be used
    to customize the agent's behavior for this specific user.
    
    The config includes:
    - technical_tone: How technical the agent should be
    - risk_tolerance: How the agent handles risk scenarios
    - sanitary_framework: Approach to pest/disease management
    - priority: What the agent should prioritize
    - alert_threshold: When to alert the user
    """
    context = await profile_service.get_profile_context(current_user.id)
    if not context:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Please complete enrollment first."
        )
    return context
