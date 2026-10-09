from datetime import datetime
from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .service import ReportsService
from .schemas import Report, ReportCreate, ReportUpdate

router = APIRouter(prefix="/reports", tags=["Reports"])

REPORTS = Provide["application.reports_service"]



@_both(router.post, "", response_model=Report, status_code=status.HTTP_201_CREATED, summary="Create Report")
@inject
async def create_report(
    body: ReportCreate, actor: Actor = Depends(get_actor), reports: ReportsService = Depends(REPORTS)
):
    return await reports.create_report(actor, body)


@_both(router.get, "", response_model=List[Report], summary="List Reports")
@inject
async def list_reports(
    field_id: Optional[UUID] = None,
    crop_cycle_id: Optional[UUID] = None,
    report_type: Optional[str] = None,
    zone_id: Optional[UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    actor: Actor = Depends(get_actor),
    reports: ReportsService = Depends(REPORTS),
):
    """crop_cycle_id also returns the zone tracking reports that covered that cycle."""
    return await reports.list_reports(
        actor,
        field_id=field_id,
        crop_cycle_id=crop_cycle_id,
        report_type=report_type,
        skip=skip,
        limit=limit,
        zone_id=zone_id,
        since=since,
        until=until,
    )


@router.get("/{report_id}", response_model=Report, summary="Get Report")
@inject
async def get_report(report_id: UUID, actor: Actor = Depends(get_actor), reports: ReportsService = Depends(REPORTS)):
    return await reports.get_report(actor, report_id)


@router.put("/{report_id}", response_model=Report, summary="Update Report")
@inject
async def update_report(
    report_id: UUID, body: ReportUpdate, actor: Actor = Depends(get_actor), reports: ReportsService = Depends(REPORTS)
):
    return await reports.update_report(actor, report_id, body)


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Report")
@inject
async def delete_report(report_id: UUID, actor: Actor = Depends(get_actor), reports: ReportsService = Depends(REPORTS)):
    await reports.delete_report(actor, report_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
