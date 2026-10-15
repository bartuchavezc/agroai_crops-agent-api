from __future__ import annotations

from typing import Any, Callable, Optional, Sequence
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import CropMaster
from src.application.planning.models import PlanSowing

from .models import SeedLot

LotWithCrop = tuple[SeedLot, CropMaster]


def _norm_variety(value: Optional[str]) -> str:
    return (value or "").strip().lower()


class SeedLotRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    def _visible(self, account_id: UUID):
        return (
            select(SeedLot, CropMaster)
            .join(CropMaster, CropMaster.id == SeedLot.crop_master_id)
            .where(SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None))
        )

    async def list(
        self,
        account_id: UUID,
        crop_master_id: Optional[UUID] = None,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        in_stock: Optional[bool] = None,
    ) -> Sequence[LotWithCrop]:
        stmt = self._visible(account_id)
        if crop_master_id:
            stmt = stmt.where(SeedLot.crop_master_id == crop_master_id)
        # Every word has to appear somewhere: "tomate platense" finds the crop name plus the lot's variety.
        for word in (query or "").split():
            like = f"%{word}%"
            stmt = stmt.where(
                or_(
                    CropMaster.name.ilike(like),
                    CropMaster.variety.ilike(like),
                    CropMaster.family.ilike(like),
                    SeedLot.variety_note.ilike(like),
                    SeedLot.source.ilike(like),
                    func.array_to_string(SeedLot.tags, " ").ilike(like),
                )
            )
        if tags:
            stmt = stmt.where(SeedLot.tags.contains(cast(tags, SeedLot.tags.type)))
        if in_stock is True:
            stmt = stmt.where(SeedLot.quantity > 0)
        elif in_stock is False:
            stmt = stmt.where(SeedLot.quantity <= 0)
        stmt = stmt.order_by(SeedLot.expiry_date.asc().nulls_last(), SeedLot.created_at.desc())
        async with self.session_factory() as session:
            return [tuple(row) for row in (await session.execute(stmt)).all()]

    async def get(self, account_id: UUID, lot_id: UUID) -> Optional[LotWithCrop]:
        async with self.session_factory() as session:
            row = (await session.execute(self._visible(account_id).where(SeedLot.id == lot_id))).first()
        return tuple(row) if row else None

    async def find_matching(
        self, account_id: UUID, crop_master_id: UUID, variety_note: Optional[str], exclude_id: Optional[UUID] = None
    ) -> Optional[LotWithCrop]:
        """The most recent lot of the same crop and variety (variety compared trimmed and case-insensitive)."""
        stmt = (
            self._visible(account_id)
            .where(
                SeedLot.crop_master_id == crop_master_id,
                func.lower(func.coalesce(func.btrim(SeedLot.variety_note), "")) == _norm_variety(variety_note),
            )
            .order_by(SeedLot.created_at.desc())
            .limit(1)
        )
        if exclude_id:
            stmt = stmt.where(SeedLot.id != exclude_id)
        async with self.session_factory() as session:
            row = (await session.execute(stmt)).first()
        return tuple(row) if row else None

    async def create(self, lot: SeedLot) -> SeedLot:
        async with self.session_factory() as session:
            session.add(lot)
            await session.commit()
            await session.refresh(lot)
        return lot

    async def apply(
        self, account_id: UUID, lot_id: UUID, mutate: Callable[[SeedLot, CropMaster], Any]
    ) -> Optional[tuple[SeedLot, CropMaster, Any]]:
        """Read-modify-write under a row lock, so two quick adjustments don't overwrite each other.
        `mutate` changes the lot in place and may return extra info (or raise to abort)."""
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    self._visible(account_id).where(SeedLot.id == lot_id).with_for_update(of=SeedLot)
                )
            ).first()
            if row is None:
                return None
            lot, crop = row
            info = mutate(lot, crop)
            await session.commit()
            await session.refresh(lot)
        return lot, crop, info

    async def update(self, account_id: UUID, lot_id: UUID, values: dict[str, Any]) -> Optional[SeedLot]:
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
            for key, value in values.items():
                setattr(lot, key, value)
            await session.commit()
            await session.refresh(lot)
        return lot

    async def merge(
        self, account_id: UUID, target_id: UUID, source_ids: list[UUID], values: dict[str, Any]
    ) -> Optional[SeedLot]:
        """One transaction: update the target, point planned sowings at it, soft-delete the sources."""
        async with self.session_factory() as session:
            target = (
                await session.execute(
                    select(SeedLot).where(
                        SeedLot.id == target_id, SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if target is None:
                return None
            for key, value in values.items():
                setattr(target, key, value)
            await session.execute(
                update(PlanSowing)
                .where(PlanSowing.account_id == account_id, PlanSowing.seed_lot_id.in_(source_ids))
                .values(seed_lot_id=target_id)
            )
            await session.execute(
                update(SeedLot)
                .where(SeedLot.id.in_(source_ids), SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
            await session.refresh(target)
        return target

    async def tag_counts(self, account_id: UUID) -> list[tuple[str, int]]:
        tag = func.unnest(SeedLot.tags).label("tag")
        sub = (
            select(tag).where(SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None)).subquery()
        )
        stmt = (
            select(cast(sub.c.tag, String), func.count())
            .group_by(sub.c.tag)
            .order_by(func.count().desc(), sub.c.tag)
        )
        async with self.session_factory() as session:
            return [(t, n) for t, n in (await session.execute(stmt)).all()]

    async def delete(self, account_id: UUID, lot_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(SeedLot)
                .where(SeedLot.id == lot_id, SeedLot.account_id == account_id, SeedLot.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0
