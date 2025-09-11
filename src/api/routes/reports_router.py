"""
Reports API routes for FastAPI.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from uuid import UUID
from typing import List
import logging
from dependency_injector.wiring import inject, Provide

from src.app.container import Container
from src.app.reports.service.reports_service import ReportsService
from src.app.reports.domain.models import Report as ReportDTO  # Renamed to avoid clash with pydantic.BaseModel

router = APIRouter(
    prefix="/reports",
    tags=["Reports"],
)

logger = logging.getLogger(__name__)

@router.get(
    "/{report_id}", 
    response_model=ReportDTO, 
    summary="Get Report by ID",
    description="Retrieves a specific report by its UUID."
)
@inject
async def get_report_by_id_endpoint(
    report_id: UUID,
    reports_service: ReportsService = Depends(Provide[Container.reports.reports_service])
):
    try:
        report = await reports_service.get_report_by_id(report_id)
        if not report:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Report with ID {report_id} not found")
        return ReportDTO.model_validate(report) # Pydantic v2 directly returns model
    except HTTPException: # Re-raise HTTPException to be handled by FastAPI
        raise
    except Exception as e:
        logger.error(f"Error retrieving report {report_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get(
    "/", 
    response_model=List[ReportDTO], 
    summary="List Reports",
    description="Retrieves a list of reports, with optional pagination."
)
@inject
async def list_reports_endpoint(
    skip: int = Query(0, ge=0, description="Number of records to skip for pagination."),
    limit: int = Query(100, ge=1, le=200, description="Maximum number of records to return."),
    reports_service: ReportsService = Depends(Provide[Container.reports.reports_service])
):
    try:
        reports = await reports_service.list_reports(skip=skip, limit=limit)
        # FastAPI will automatically call model_dump() when returning Pydantic models in a list
        return [ReportDTO.model_validate(r) for r in reports]
    except Exception as e:
        logger.error(f"Error listing reports: {str(e)}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

# No public endpoints for CREATE, UPDATE, DELETE as per requirements.

# If you have a global error handler, make sure to register it.
# reports_bp.register_error_handler(NotFoundError, handle_api_error) 