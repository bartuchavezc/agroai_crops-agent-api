from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.repositories.report_campaign_repository import ReportCampaignRepositoryInterface
from src.app.farm_management.domain.schemas.report_campaign_schema import ReportCampaignLink, ReportCampaignRead
# For validation, you might need ReportRepository and CropCycleRepository if not already handled by DB constraints
# from src.app.reports.domain.repositories.report_repository import ReportRepositoryInterface 
# from src.app.farm_management.domain.repositories.crop_cycle_repository import CropCycleRepositoryInterface
# from src.app.common.exceptions import NotFoundException

class ReportCampaignService:
    def __init__(self, 
                 report_campaign_repository: ReportCampaignRepositoryInterface
                 # report_repository: ReportRepositoryInterface, # Optional, for validation
                 # crop_cycle_repository: CropCycleRepositoryInterface # Optional, for validation
                ):
        self._repository = report_campaign_repository
        # self._report_repository = report_repository 
        # self._crop_cycle_repository = crop_cycle_repository

    async def link_report_to_crop_cycle(self, link_data: ReportCampaignLink) -> ReportCampaignRead:
        # Business logic: Validate report_id and crop_cycle_id exist before linking
        # report = await self._report_repository.get_by_id(link_data.report_id)
        # if not report:
        #     raise NotFoundException(f"Report {link_data.report_id} not found.")
        # crop_cycle = await self._crop_cycle_repository.get_by_id(link_data.crop_cycle_id)
        # if not crop_cycle:
        #     raise NotFoundException(f"Crop cycle {link_data.crop_cycle_id} not found.")

        # The repository's link_report_to_cycle handles potential IntegrityError (e.g. duplicate link)
        link = await self._repository.link_report_to_cycle(link_data)
        return ReportCampaignRead.model_validate(link)

    async def unlink_report_from_crop_cycle(self, report_id: UUID, crop_cycle_id: UUID) -> bool:
        was_unlinked = await self._repository.unlink_report_from_cycle(report_id, crop_cycle_id)
        # if not was_unlinked:
            # raise NotFoundException(f"Link between report {report_id} and crop cycle {crop_cycle_id} not found.")
        return was_unlinked

    async def get_links_for_report(self, report_id: UUID) -> List[ReportCampaignRead]:
        links = await self._repository.get_by_report_id(report_id)
        return [ReportCampaignRead.model_validate(link) for link in links]

    async def get_links_for_crop_cycle(self, crop_cycle_id: UUID) -> List[ReportCampaignRead]:
        links = await self._repository.get_by_crop_cycle_id(crop_cycle_id)
        return [ReportCampaignRead.model_validate(link) for link in links]
    
    async def get_specific_link(self, report_id: UUID, crop_cycle_id: UUID) -> Optional[ReportCampaignRead]:
        link = await self._repository.get_link(report_id, crop_cycle_id)
        if not link:
            return None
        return ReportCampaignRead.model_validate(link) 