from abc import ABC, abstractmethod
from typing import Optional, List
from uuid import UUID

from src.app.farm_management.domain.report_campaign_model import ReportCampaignModel
from src.app.farm_management.domain.schemas.report_campaign_schema import ReportCampaignLink

class ReportCampaignRepositoryInterface(ABC):
    @abstractmethod
    async def link_report_to_cycle(self, link_data: ReportCampaignLink) -> ReportCampaignModel:
        pass

    @abstractmethod
    async def unlink_report_from_cycle(self, report_id: UUID, crop_cycle_id: UUID) -> bool:
        pass

    @abstractmethod
    async def get_by_report_id(self, report_id: UUID) -> List[ReportCampaignModel]:
        pass

    @abstractmethod
    async def get_by_crop_cycle_id(self, crop_cycle_id: UUID) -> List[ReportCampaignModel]:
        pass
        
    @abstractmethod
    async def get_link(self, report_id: UUID, crop_cycle_id: UUID) -> Optional[ReportCampaignModel]:
        pass 