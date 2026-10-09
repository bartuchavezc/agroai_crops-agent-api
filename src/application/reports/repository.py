"""
Reports persistence, scoped by account.
"""
import uuid
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.database import Base
from src.shared.domain.base import utcnow

from .schemas import Report, ReportCreate, ReportUpdate


class ReportModel(Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_account_created", "account_id", "created_at"),
        Index("ix_reports_zone_created", "zone_id", "created_at"),
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(PGUUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(PGUUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    crop_cycle_id = Column(PGUUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"))
    # Zone tracking: one report covers every active crop of the zone (crop_cycle_ids), from 1-4 photos.
    zone_id = Column(PGUUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    crop_cycle_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    image_identifiers = Column(JSONB, nullable=False, default=list, server_default="[]")
    created_by = Column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    title = Column(String(255))
    summary = Column(Text)
    recommendations = Column(Text)
    image_identifier = Column(String(255))
    raw_analysis_data = Column(JSONB)
    analysis_id = Column(PGUUID(as_uuid=True))
    status = Column(String(50), nullable=False, default="PENDING_ANALYSIS")
    report_type = Column(String(20), nullable=False, default="diagnosis")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class SQLAlchemyReportsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, account_id: UUID, created_by: Optional[UUID], data: ReportCreate) -> Report:
        values = data.model_dump()
        values["crop_cycle_ids"] = [str(c) for c in data.crop_cycle_ids]  # JSONB
        model = ReportModel(account_id=account_id, created_by=created_by, **values)
        async with self.session_factory() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return Report.model_validate(model)

    async def get_by_id(self, account_id: UUID, report_id: UUID) -> Optional[Report]:
        async with self.session_factory() as session:
            model = (
                await session.execute(
                    select(ReportModel).where(ReportModel.id == report_id, ReportModel.account_id == account_id)
                )
            ).scalar_one_or_none()
        return Report.model_validate(model) if model else None

    async def list(
        self,
        account_id: UUID,
        field_id: Optional[UUID] = None,
        crop_cycle_id: Optional[UUID] = None,
        report_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
        zone_id: Optional[UUID] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        status: Optional[str] = None,
    ) -> List[Report]:
        stmt = select(ReportModel).where(ReportModel.account_id == account_id)
        if field_id:
            stmt = stmt.where(ReportModel.field_id == field_id)
        if crop_cycle_id:
            # Its own reports plus the zone tracking reports that covered it.
            stmt = stmt.where(
                or_(
                    ReportModel.crop_cycle_id == crop_cycle_id,
                    ReportModel.crop_cycle_ids.contains([str(crop_cycle_id)]),
                )
            )
        if zone_id:
            stmt = stmt.where(ReportModel.zone_id == zone_id)
        if report_type:
            stmt = stmt.where(ReportModel.report_type == report_type)
        if status:
            stmt = stmt.where(ReportModel.status == status)
        if since:
            stmt = stmt.where(ReportModel.created_at >= since)
        if until:
            stmt = stmt.where(ReportModel.created_at <= until)
        stmt = stmt.order_by(ReportModel.created_at.desc()).offset(skip).limit(limit)
        async with self.session_factory() as session:
            return [Report.model_validate(r) for r in (await session.execute(stmt)).scalars().all()]

    async def update(self, account_id: UUID, report_id: UUID, data: ReportUpdate) -> Optional[Report]:
        async with self.session_factory() as session:
            model = (
                await session.execute(
                    select(ReportModel).where(ReportModel.id == report_id, ReportModel.account_id == account_id)
                )
            ).scalar_one_or_none()
            if model is None:
                return None
            for key, value in data.model_dump(exclude_unset=True).items():
                setattr(model, key, value)
            model.updated_at = utcnow()
            await session.commit()
            await session.refresh(model)
        return Report.model_validate(model)

    async def delete(self, account_id: UUID, report_id: UUID) -> bool:
        async with self.session_factory() as session:
            model = (
                await session.execute(
                    select(ReportModel).where(ReportModel.id == report_id, ReportModel.account_id == account_id)
                )
            ).scalar_one_or_none()
            if model is None:
                return False
            await session.delete(model)
            await session.commit()
        return True
