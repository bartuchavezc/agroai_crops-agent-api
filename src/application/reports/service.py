from typing import List, Optional
from uuid import UUID

from src.shared.domain.actor import Actor
from src.shared.utils.errors import NotFoundError, PermissionDeniedError

from .repository import SQLAlchemyReportsRepository
from .schemas import Report, ReportCreate, ReportUpdate


class ReportsService:
    def __init__(self, reports_repository: SQLAlchemyReportsRepository, farm_service=None):
        self.repo = reports_repository
        self.farm = farm_service

    async def _check_links(self, actor: Actor, field_id: Optional[UUID], crop_cycle_id: Optional[UUID]) -> None:
        if self.farm is None:
            return
        if field_id:
            await self.farm.get_field(actor, field_id)
        if crop_cycle_id:
            await self.farm.get_crop_cycle(actor, crop_cycle_id)

    async def create_report(self, actor: Actor, data: ReportCreate) -> Report:
        await self._check_links(actor, data.field_id, data.crop_cycle_id)
        if self.farm is not None and data.zone_id:
            await self.farm.get_zone(actor, data.zone_id)
        if self.farm is not None and data.crop_cycle_id and not data.zone_id:
            # A photo of one crop is also part of its zone's history.
            cycle = await self.farm.get_crop_cycle(actor, data.crop_cycle_id)
            data = data.model_copy(update={"zone_id": cycle.zone_id})
        return await self.repo.create(actor.account_id, actor.user_id, data)

    async def get_report(self, actor: Actor, report_id: UUID) -> Report:
        report = await self.repo.get_by_id(actor.account_id, report_id)
        if report is None:
            raise NotFoundError(f"Report {report_id} not found.")
        return report

    async def list_reports(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        crop_cycle_id: Optional[UUID] = None,
        report_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        zone_id: Optional[UUID] = None,
    ) -> List[Report]:
        """crop_cycle_id also matches zone tracking reports that covered that cycle."""
        return await self.repo.list(
            actor.account_id,
            field_id=field_id,
            crop_cycle_id=crop_cycle_id,
            report_type=report_type,
            skip=skip,
            limit=min(limit, 500),
            zone_id=zone_id,
        )

    async def update_report(self, actor: Actor, report_id: UUID, data: ReportUpdate) -> Report:
        await self._check_links(actor, data.field_id, data.crop_cycle_id)
        report = await self.repo.update(actor.account_id, report_id, data)
        if report is None:
            raise NotFoundError(f"Report {report_id} not found.")
        return report

    async def delete_report(self, actor: Actor, report_id: UUID) -> None:
        report = await self.get_report(actor, report_id)
        if not actor.is_manager and report.created_by != actor.user_id:
            raise PermissionDeniedError("You can only delete reports you created.")
        if not await self.repo.delete(actor.account_id, report_id):
            raise NotFoundError(f"Report {report_id} not found.")
