"""
Platform admin endpoints (read-only business metrics for agroai_admin). Only PLATFORM_ADMIN_EMAILS get in;
anyone else gets a 404.
"""
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query

from src.auth.api.dependencies import require_platform_admin
from src.auth.domain.schemas import UserRead

from .schemas import AdminAccountRow, AdminUserRow, Overview, Timeseries
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


@router.get("/accounts", response_model=list[AdminAccountRow], summary="Every account with usage counters")
@inject
async def accounts(
    _: UserRead = Depends(require_platform_admin),
    service: AdminMetricsService = Depends(Provide["admin_metrics_service"]),
):
    return await service.accounts()
