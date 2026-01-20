# src/action/api/reports_router.py
"""
Reports API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide
from typing import List
from uuid import UUID

from ..reports.schemas import Report, ReportCreate, ReportUpdate

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post("", response_model=Report, status_code=status.HTTP_201_CREATED, summary="Create Report")
@inject
async def create_report(
    report_create: ReportCreate,
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    Create a new report entry.
    """
    return await reports_service.create_report(report_create)


@router.get("", response_model=List[Report], summary="List Reports")
@inject
async def list_reports(
    skip: int = 0,
    limit: int = 100,
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    List all reports with pagination.
    """
    return await reports_service.list_reports(skip=skip, limit=limit)


@router.get("/{report_id}", response_model=Report, summary="Get Report")
@inject
async def get_report(
    report_id: UUID,
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    Get a specific report by ID.
    """
    report = await reports_service.get_report_by_id(report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} not found"
        )
    return report


@router.put("/{report_id}", response_model=Report, summary="Update Report")
@inject
async def update_report(
    report_id: UUID,
    report_update: ReportUpdate,
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    Update an existing report.
    """
    report = await reports_service.update_report(report_id, report_update)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} not found"
        )
    return report


@router.delete("/{report_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Report")
@inject
async def delete_report(
    report_id: UUID,
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    Delete a report.
    """
    report = await reports_service.delete_report(report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report with ID {report_id} not found"
        )
    return None
