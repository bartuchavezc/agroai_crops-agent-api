from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update as sqlalchemy_update, delete as sqlalchemy_delete, func

from src.app.reports.domain.models import Report, ReportCreate, ReportUpdate
from src.app.reports.domain.repositories import ReportsRepository
from src.app.reports.domain.report_model import ReportModel
from datetime import datetime, timezone

class SQLReportsRepository(ReportsRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, report_id: UUID) -> Optional[Report]:
        result = await self.session.execute(
            select(ReportModel).filter(ReportModel.id == report_id)
        )
        db_report = result.scalars().first()
        if db_report:
            return Report.model_validate(db_report)
        return None

    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Report]:
        result = await self.session.execute(
            select(ReportModel).offset(skip).limit(limit)
        )
        db_reports = result.scalars().all()
        return [Report.model_validate(db_report) for db_report in db_reports]

    async def create(self, report_create: ReportCreate) -> Report:
        db_report = ReportModel(**report_create.model_dump())
        # Pydantic V2 usa model_dump() en lugar de dict()
        # db_report = ReportModel(**report_create.dict()) 
        
        self.session.add(db_report)
        await self.session.commit()
        await self.session.refresh(db_report)
        return Report.model_validate(db_report)

    async def update(self, report_id: UUID, report_update: ReportUpdate) -> Optional[Report]:
        update_data = report_update.model_dump(exclude_unset=True)
        # Pydantic V2 usa model_dump(exclude_unset=True) en lugar de dict(exclude_unset=True)
        # update_data = report_update.dict(exclude_unset=True)
        
        if not update_data:
            # No hay nada que actualizar, podríamos devolver el objeto existente o None/error
            return await self.get_by_id(report_id)

        update_data['updated_at'] = datetime.now(timezone.utc)

        stmt = (
            sqlalchemy_update(ReportModel)
            .where(ReportModel.id == report_id)
            .values(**update_data)
            .returning(ReportModel)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        updated_db_report = result.scalars().first()
        
        if updated_db_report:
            return Report.model_validate(updated_db_report)
        return None

    async def delete(self, report_id: UUID) -> Optional[Report]:
        report_to_delete = await self.get_by_id(report_id)
        if not report_to_delete:
            return None
        
        stmt = sqlalchemy_delete(ReportModel).where(ReportModel.id == report_id)
        await self.session.execute(stmt)
        await self.session.commit()
        return report_to_delete 