# src/action/reports/report_repository.py
"""
Report repository interface and implementations.
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
import logging

from sqlalchemy import Column, DateTime, String, JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select
import uuid

from src.shared.database import shared_metadata
from src.shared.domain.base import DomainBase
from .schemas import Report, ReportCreate, ReportUpdate

logger = logging.getLogger(__name__)


# SQLAlchemy Model
class ReportModel(DomainBase):
    """SQLAlchemy model for reports."""
    __tablename__ = "reports"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255))
    summary = Column(String)
    recommendations = Column(String)
    image_identifier = Column(String)
    raw_analysis_data = Column(JSON)
    analysis_id = Column(PGUUID(as_uuid=True), nullable=True)
    status = Column(String(50), default="PENDING_ANALYSIS")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )


class ReportsRepository(ABC):
    """Abstract repository interface for reports."""
    
    @abstractmethod
    async def create(self, report_create: ReportCreate) -> Report:
        """Create a new report."""
        pass

    @abstractmethod
    async def get_by_id(self, report_id: UUID) -> Optional[Report]:
        """Get report by ID."""
        pass

    @abstractmethod
    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Report]:
        """List all reports."""
        pass

    @abstractmethod
    async def update(self, report_id: UUID, report_update: ReportUpdate) -> Optional[Report]:
        """Update a report."""
        pass

    @abstractmethod
    async def delete(self, report_id: UUID) -> Optional[Report]:
        """Delete a report."""
        pass


class SQLAlchemyReportsRepository(ReportsRepository):
    """SQLAlchemy implementation of reports repository."""
    
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, report_create: ReportCreate) -> Report:
        """Create a new report."""
        db_report = ReportModel(
            **report_create.model_dump()
        )
        
        async with self.session_factory() as session:
            async with session.begin():
                session.add(db_report)
            await session.commit()
            await session.refresh(db_report)
        
        return Report.model_validate(db_report)

    async def get_by_id(self, report_id: UUID) -> Optional[Report]:
        """Get report by ID."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReportModel).filter(ReportModel.id == report_id)
            )
            db_report = result.scalars().first()
            
            if db_report:
                return Report.model_validate(db_report)
            return None

    async def list_all(self, skip: int = 0, limit: int = 100) -> List[Report]:
        """List all reports with pagination."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReportModel)
                .order_by(ReportModel.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            db_reports = result.scalars().all()
            
            return [Report.model_validate(r) for r in db_reports]

    async def update(self, report_id: UUID, report_update: ReportUpdate) -> Optional[Report]:
        """Update a report."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReportModel).filter(ReportModel.id == report_id)
            )
            db_report = result.scalars().first()
            
            if not db_report:
                return None
            
            # Update fields
            update_data = report_update.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_report, key, value)
            
            db_report.updated_at = datetime.now(timezone.utc)
            
            await session.commit()
            await session.refresh(db_report)
            
            return Report.model_validate(db_report)

    async def delete(self, report_id: UUID) -> Optional[Report]:
        """Delete a report."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(ReportModel).filter(ReportModel.id == report_id)
            )
            db_report = result.scalars().first()
            
            if not db_report:
                return None
            
            report = Report.model_validate(db_report)
            await session.delete(db_report)
            await session.commit()
            
            return report
