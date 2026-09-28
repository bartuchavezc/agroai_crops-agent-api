from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import SeedLot


class SeedLotRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def list(self, account_id: UUID, crop_master_id: Optional[UUID] = None) -> Sequence[SeedLot]:
        stmt = select(SeedLot).where(SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None))
        if crop_master_id:
            stmt = stmt.where(SeedLot.crop_master_id == crop_master_id)
        stmt = stmt.order_by(SeedLot.expiry_date.asc().nulls_last(), SeedLot.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get(self, account_id: UUID, lot_id: UUID) -> Optional[SeedLot]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(SeedLot).where(
                        SeedLot.id == lot_id, SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()

    async def create(self, lot: SeedLot) -> SeedLot:
        async with self.session_factory() as session:
            session.add(lot)
            await session.commit()
            await session.refresh(lot)
        return lot

    async def adjust_quantity(self, account_id: UUID, lot_id: UUID, delta: float) -> Optional[SeedLot]:
        async with self.session_factory() as session:
            lot = (
                await session.execute(
                    select(SeedLot).where(
                        SeedLot.id == lot_id, SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if lot is None:
                return None
            lot.quantity = max(0.0, lot.quantity + delta)
            await session.commit()
            await session.refresh(lot)
        return lot

    async def delete(self, account_id: UUID, lot_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(SeedLot)
                .where(SeedLot.id == lot_id, SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0
