from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from .models import Report, ReportCreate, ReportUpdate

class ReportsRepository(ABC):

    @abstractmethod
    async def get_by_id(self, report_id: UUID) -> Optional[Report]:
        pass

    @abstractmethod
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Report]:
        pass

    @abstractmethod
    async def create(self, report_create: ReportCreate) -> Report:
        pass

    @abstractmethod
    async def update(self, report_id: UUID, report_update: ReportUpdate) -> Optional[Report]:
        pass

    @abstractmethod
    async def delete(self, report_id: UUID) -> Optional[Report]:
        pass 