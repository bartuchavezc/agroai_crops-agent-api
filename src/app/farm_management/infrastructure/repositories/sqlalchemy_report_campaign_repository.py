from typing import Optional, List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select, delete as sqlalchemy_delete, and_
from sqlalchemy.exc import IntegrityError

from src.app.farm_management.domain.report_campaign_model import ReportCampaignModel
from src.app.farm_management.domain.schemas.report_campaign_schema import ReportCampaignLink
from src.app.farm_management.domain.repositories.report_campaign_repository import ReportCampaignRepositoryInterface

class SQLAlchemyReportCampaignRepository(ReportCampaignRepositoryInterface):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def link_report_to_cycle(self, link_data: ReportCampaignLink) -> ReportCampaignModel:
        db_link = ReportCampaignModel(**link_data.model_dump())
        async with self._session_factory() as session:
            try:
                session.add(db_link)
                await session.commit()
                await session.refresh(db_link)
                return db_link
            except IntegrityError: # Handles cases like duplicate primary key or foreign key violation
                await session.rollback()
                # Optionally, fetch existing if it's a duplicate PK error and makes sense
                existing = await self.get_link(link_data.report_id, link_data.crop_cycle_id)
                if existing: return existing
                raise # Re-raise if it's another integrity error (e.g. FK not found)

    async def unlink_report_from_cycle(self, report_id: UUID, crop_cycle_id: UUID) -> bool:
        async with self._session_factory() as session:
            stmt = sqlalchemy_delete(ReportCampaignModel).where(
                and_(
                    ReportCampaignModel.report_id == report_id,
                    ReportCampaignModel.crop_cycle_id == crop_cycle_id
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def get_by_report_id(self, report_id: UUID) -> List[ReportCampaignModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportCampaignModel).filter(ReportCampaignModel.report_id == report_id)
            )
            return result.scalars().all()

    async def get_by_crop_cycle_id(self, crop_cycle_id: UUID) -> List[ReportCampaignModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportCampaignModel).filter(ReportCampaignModel.crop_cycle_id == crop_cycle_id)
            )
            return result.scalars().all()
            
    async def get_link(self, report_id: UUID, crop_cycle_id: UUID) -> Optional[ReportCampaignModel]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ReportCampaignModel).filter(
                    and_(
                        ReportCampaignModel.report_id == report_id,
                        ReportCampaignModel.crop_cycle_id == crop_cycle_id
                    )
                )
            )
            return result.scalars().first() 