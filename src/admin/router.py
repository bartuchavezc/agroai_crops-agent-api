"""
Platform admin endpoints for agroai_admin: business metrics, plus adding account owners and enabling or disabling
users. Only PLATFORM_ADMIN_EMAILS get in; anyone else gets a 404.
"""
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.auth.api.dependencies import require_platform_admin
from src.auth.domain.schemas import SignupRequest, UserRead
from src.auth.services.user_service import UserService
from src.shared.utils.errors import UserAlreadyExistsError

from .schemas import AdminAccountRow, AdminUserRow, AdminUserStatus, Overview, Timeseries
from .service import AdminMetricsService

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/me", summary="The platform admin's own identity")
async def admin_me(admin: UserRead = Depends(require_platform_admin)):
    return {"id": admin.id, "email": admin.email, "first_name": admin.first_name, "last_name": admin.last_name}


@router.get("/overview", response_model=Overview, summary="KPIs over the whole platform")
@inject
async def overview(
    days: int = Query(30, ge=1, le=365, description="Window for the 'in window' / recent figures"),
    _: UserRead = Depends(require_platform_admin),
    service: AdminMetricsService = Depends(Provide["admin_metrics_service"]),
):
    return await service.overview(days)


@router.get("/timeseries", response_model=Timeseries, summary="Daily activity, in the app timezone")
@inject
async def timeseries(
    days: int = Query(30, ge=7, le=365),
    _: UserRead = Depends(require_platform_admin),
    service: AdminMetricsService = Depends(Provide["admin_metrics_service"]),
):
    return await service.timeseries(days)


@router.get("/users", response_model=list[AdminUserRow], summary="Every user with usage counters")
@inject
async def users(
    _: UserRead = Depends(require_platform_admin),
    service: AdminMetricsService = Depends(Provide["admin_metrics_service"]),
):
    return await service.users()


@router.post(
    "/users", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Add an owner (with a new account)"
)
@inject
async def create_owner(
    body: SignupRequest,
    _: UserRead = Depends(require_platform_admin),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    """Same as a public signup (works even when ALLOW_PUBLIC_SIGNUP is off); the owner then adds their members."""
    try:
        user = await user_service.create_owner(body)
    except UserAlreadyExistsError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.") from None
    return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Enable or disable a user")
@inject
async def set_user_status(
    user_id: UUID,
    body: AdminUserStatus,
    admin: UserRead = Depends(require_platform_admin),
    user_service: UserService = Depends(Provide["auth.user_service"]),
):
    """A disabled user can't log in and their open sessions stop working right away; their records stay."""
    if user_id == admin.id and not body.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot disable yourself.")
    user = await user_service.set_active(user_id, body.is_active)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/accounts", response_model=list[AdminAccountRow], summary="Every account with usage counters")
@inject
async def accounts(
    _: UserRead = Depends(require_platform_admin),
    service: AdminMetricsService = Depends(Provide["admin_metrics_service"]),
):
    return await service.accounts()
