from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import ZoneSatelliteReading


class ZoneSatelliteRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def create(self, reading: ZoneSatelliteReading) -> ZoneSatelliteReading:
        async with self.session_factory() as session:
            session.add(reading)
            await session.commit()
            await session.refresh(reading)
        return reading

    async def latest(self, account_id: UUID, field_id: UUID) -> Optional[ZoneSatelliteReading]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(ZoneSatelliteReading)
                    .where(ZoneSatelliteReading.account_id == account_id, ZoneSatelliteReading.field_id == field_id)
                    .order_by(ZoneSatelliteReading.captured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def latest_image(self, account_id: UUID, field_id: UUID) -> Optional[str]:
        """The most recent reading that actually has a saved image — not necessarily the most recent
        reading overall, since a stats-only check_field() row has none."""
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(ZoneSatelliteReading.image_identifier)
                    .where(
                        ZoneSatelliteReading.account_id == account_id,
                        ZoneSatelliteReading.field_id == field_id,
                        ZoneSatelliteReading.image_identifier.is_not(None),
                    )
                    .order_by(ZoneSatelliteReading.captured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def recent(self, account_id: UUID, field_id: UUID, limit: int = 10) -> Sequence[ZoneSatelliteReading]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(ZoneSatelliteReading)
                    .where(ZoneSatelliteReading.account_id == account_id, ZoneSatelliteReading.field_id == field_id)
                    .order_by(ZoneSatelliteReading.captured_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
