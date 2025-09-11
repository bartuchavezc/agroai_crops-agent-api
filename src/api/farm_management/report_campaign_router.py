from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from uuid import UUID
from dependency_injector.wiring import inject, Provide

from src.app.farm_management.service.report_campaign_service import ReportCampaignService
from src.app.farm_management.domain.schemas.report_campaign_schema import ReportCampaignLink, ReportCampaignRead
from src.app.container import Container # Import the root container
# from src.app.users.service.auth_service import get_current_active_user

router = APIRouter(
    tags=["Farm Management - Report Campaigns"],
    # dependencies=[Depends(get_current_active_user)]
)

@router.post("/report-campaigns/link/", response_model=ReportCampaignRead, status_code=status.HTTP_201_CREATED)
@inject
async def link_report_to_crop_cycle(
    link_in: ReportCampaignLink,
    service: ReportCampaignService = Depends(Provide[Container.farm_management.report_campaign_service])
):
    # Service might raise NotFoundException if report_id or crop_cycle_id don't exist
    # Repository handles IntegrityError for duplicate links.
    link = await service.link_report_to_crop_cycle(link_in)
    return link

@router.delete("/report-campaigns/unlink/", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def unlink_report_from_crop_cycle(
    report_id: UUID,
    crop_cycle_id: UUID, # Or send as a DTO body if preferred
    service: ReportCampaignService = Depends(Provide[Container.farm_management.report_campaign_service])
):
    # TODO: Authorization checks
    unlinked = await service.unlink_report_from_crop_cycle(report_id, crop_cycle_id)
    if not unlinked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found or could not be removed")
    return None

@router.get("/reports/{report_id}/campaign-links/", response_model=List[ReportCampaignRead])
@inject
async def read_links_for_report(
    report_id: UUID,
    service: ReportCampaignService = Depends(Provide[Container.farm_management.report_campaign_service])
):
    # TODO: Authorization checks
    links = await service.get_links_for_report(report_id)
    return links

@router.get("/crop-cycles/{crop_cycle_id}/campaign-links/", response_model=List[ReportCampaignRead])
@inject
async def read_links_for_crop_cycle(
    crop_cycle_id: UUID,
    service: ReportCampaignService = Depends(Provide[Container.farm_management.report_campaign_service])
):
    # TODO: Authorization checks
    links = await service.get_links_for_crop_cycle(crop_cycle_id)
    return links

@router.get("/report-campaigns/link/", response_model=ReportCampaignRead) # Query params for GET
@inject
async def read_specific_link(
    report_id: UUID,
    crop_cycle_id: UUID,
    service: ReportCampaignService = Depends(Provide[Container.farm_management.report_campaign_service])
):
    link = await service.get_specific_link(report_id, crop_cycle_id)
    if link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    return link 