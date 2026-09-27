"""
Farm data access. Every query takes account_id; nothing here is reachable across accounts.
"""
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import ACTIVE_CROP_CYCLE_STATUSES, CropCycle, CropMaster, Field, FieldEvent


class FarmRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    # ---------- generic helpers ----------

    async def _add(self, obj):
        async with self.session_factory() as session:
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
        return obj

    @staticmethod
    def _not_deleted(model, conditions: list) -> list:
        """Excludes soft-deleted rows for models that carry a `deleted_at` column; a no-op otherwise
        (CropMaster and FieldEvent are hard-deleted and have no such column)."""
        if hasattr(model, "deleted_at"):
            conditions.append(model.deleted_at.is_(None))
        return conditions

    async def _update(self, model, obj_id: UUID, account_id: UUID, values: dict[str, Any]):
        conditions = self._not_deleted(model, [model.id == obj_id, model.account_id == account_id])
        async with self.session_factory() as session:
            obj = (await session.execute(select(model).where(*conditions))).scalar_one_or_none()
            if obj is None:
                return None
            for key, value in values.items():
                setattr(obj, key, value)
            await session.commit()
            await session.refresh(obj)
        return obj

    async def _delete(self, model, obj_id: UUID, account_id: UUID) -> bool:
        """Hard delete — only for models with no `deleted_at` column (CropMaster, FieldEvent)."""
        async with self.session_factory() as session:
            result = await session.execute(
                delete(model).where(model.id == obj_id, model.account_id == account_id)
            )
            await session.commit()
        return result.rowcount > 0

    async def _soft_delete(self, model, obj_id: UUID, account_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(model)
                .where(model.id == obj_id, model.account_id == account_id, model.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0

    async def _get(self, model, obj_id: UUID, account_id: UUID):
        conditions = self._not_deleted(model, [model.id == obj_id, model.account_id == account_id])
        async with self.session_factory() as session:
            return (await session.execute(select(model).where(*conditions))).scalar_one_or_none()

    # ---------- fields ----------

    async def list_fields(self, account_id: UUID) -> Sequence[Field]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Field)
                .where(Field.account_id == account_id, Field.deleted_at.is_(None))
                .order_by(Field.name)
            )
            return result.scalars().all()

    async def list_all_fields_with_coordinates(self) -> Sequence[Field]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Field).where(
                    Field.latitude.is_not(None), Field.longitude.is_not(None), Field.deleted_at.is_(None)
                )
            )
            return result.scalars().all()

    async def get_field(self, account_id: UUID, field_id: UUID) -> Optional[Field]:
        return await self._get(Field, field_id, account_id)

    async def find_fields_by_name(self, account_id: UUID, name: str) -> Sequence[Field]:
        async with self.session_factory() as session:
            exact = (
                await session.execute(
                    select(Field).where(
                        Field.account_id == account_id,
                        Field.deleted_at.is_(None),
                        func.lower(Field.name) == name.lower(),
                    )
                )
            ).scalars().all()
            if exact:
                return exact
            result = await session.execute(
                select(Field).where(
                    Field.account_id == account_id, Field.deleted_at.is_(None), Field.name.ilike(f"%{name}%")
                )
            )
            return result.scalars().all()

    async def create_field(self, field: Field) -> Field:
        return await self._add(field)

    async def update_field(self, account_id: UUID, field_id: UUID, values: dict) -> Optional[Field]:
        return await self._update(Field, field_id, account_id, values)

    async def delete_field(self, account_id: UUID, field_id: UUID) -> bool:
        return await self._soft_delete(Field, field_id, account_id)

    # ---------- crop masters ----------

    def _visible_crop_masters(self, account_id: UUID):
        return or_(CropMaster.account_id.is_(None), CropMaster.account_id == account_id)

    async def list_crop_masters(
        self, account_id: UUID, query: Optional[str] = None, skip: int = 0, limit: int = 200
    ) -> Sequence[CropMaster]:
        stmt = select(CropMaster).where(self._visible_crop_masters(account_id))
        if query:
            stmt = stmt.where(or_(CropMaster.name.ilike(f"%{query}%"), CropMaster.variety.ilike(f"%{query}%")))
        stmt = stmt.order_by(CropMaster.name, CropMaster.variety).offset(skip).limit(limit)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_visible_crop_master(self, account_id: UUID, crop_master_id: UUID) -> Optional[CropMaster]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(CropMaster).where(
                        CropMaster.id == crop_master_id, self._visible_crop_masters(account_id)
                    )
                )
            ).scalar_one_or_none()

    async def find_crop_masters_by_name(
        self, account_id: UUID, name: str, variety: Optional[str] = None
    ) -> Sequence[CropMaster]:
        stmt = select(CropMaster).where(
            self._visible_crop_masters(account_id), func.lower(CropMaster.name) == name.lower()
        )
        if variety:
            stmt = stmt.where(CropMaster.variety.ilike(f"%{variety}%"))
        # Account-specific entries win over global ones.
        stmt = stmt.order_by(CropMaster.account_id.is_(None), CropMaster.variety)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_crop_master(self, crop_master: CropMaster) -> CropMaster:
        return await self._add(crop_master)

    async def delete_crop_master(self, account_id: UUID, crop_master_id: UUID) -> bool:
        return await self._delete(CropMaster, crop_master_id, account_id)

    # ---------- crop cycles ----------

    async def list_crop_cycles(
        self,
        account_id: UUID,
        field_id: Optional[UUID] = None,
        statuses: Optional[Iterable[str]] = None,
    ) -> Sequence[CropCycle]:
        stmt = select(CropCycle).where(CropCycle.account_id == account_id, CropCycle.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(CropCycle.field_id == field_id)
        if statuses:
            stmt = stmt.where(CropCycle.status.in_(list(statuses)))
        stmt = stmt.order_by(CropCycle.planting_date.desc().nulls_last(), CropCycle.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_crop_cycle(self, account_id: UUID, cycle_id: UUID) -> Optional[CropCycle]:
        return await self._get(CropCycle, cycle_id, account_id)

    async def create_crop_cycle(self, cycle: CropCycle) -> CropCycle:
        return await self._add(cycle)

    async def update_crop_cycle(self, account_id: UUID, cycle_id: UUID, values: dict) -> Optional[CropCycle]:
        return await self._update(CropCycle, cycle_id, account_id, values)

    async def delete_crop_cycle(self, account_id: UUID, cycle_id: UUID) -> bool:
        return await self._soft_delete(CropCycle, cycle_id, account_id)

    async def active_cycles_with_crop(self, account_id: UUID) -> list[tuple[CropCycle, CropMaster]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(CropCycle, CropMaster)
                .join(CropMaster, CropMaster.id == CropCycle.crop_master_id)
                .where(
                    CropCycle.account_id == account_id,
                    CropCycle.deleted_at.is_(None),
                    CropCycle.status.in_(ACTIVE_CROP_CYCLE_STATUSES),
                )
                .order_by(CropCycle.planting_date.desc().nulls_last())
            )
            return [(row[0], row[1]) for row in result.all()]

    async def used_crop_families(self, account_id: UUID) -> set[str]:
        """Botanical families the account has ever grown (any cycle status), for knowledge-module selection."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(CropMaster.family)
                .join(CropCycle, CropCycle.crop_master_id == CropMaster.id)
                .where(
                    CropCycle.account_id == account_id,
                    CropCycle.deleted_at.is_(None),
                    CropMaster.family.is_not(None),
                )
                .distinct()
            )
            return {row[0] for row in result.all()}

    # ---------- field events ----------

    async def list_events(
        self,
        account_id: UUID,
        field_id: Optional[UUID] = None,
        crop_cycle_id: Optional[UUID] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
    ) -> Sequence[FieldEvent]:
        stmt = select(FieldEvent).where(FieldEvent.account_id == account_id)
        if field_id:
            stmt = stmt.where(FieldEvent.field_id == field_id)
        if crop_cycle_id:
            stmt = stmt.where(FieldEvent.crop_cycle_id == crop_cycle_id)
        if event_type:
            stmt = stmt.where(FieldEvent.type == event_type)
        if since:
            stmt = stmt.where(FieldEvent.occurred_at >= since)
        if until:
            stmt = stmt.where(FieldEvent.occurred_at <= until)
        stmt = stmt.order_by(FieldEvent.occurred_at.desc()).limit(limit)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_event(self, account_id: UUID, event_id: UUID) -> Optional[FieldEvent]:
        return await self._get(FieldEvent, event_id, account_id)

    async def create_event(self, event: FieldEvent) -> FieldEvent:
        return await self._add(event)

    async def update_event(self, account_id: UUID, event_id: UUID, values: dict) -> Optional[FieldEvent]:
        return await self._update(FieldEvent, event_id, account_id, values)

    async def delete_event(self, account_id: UUID, event_id: UUID) -> bool:
        return await self._delete(FieldEvent, event_id, account_id)

    async def last_event_by_field(self, account_id: UUID) -> dict[UUID, datetime]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(FieldEvent.field_id, func.max(FieldEvent.occurred_at))
                .where(FieldEvent.account_id == account_id)
                .group_by(FieldEvent.field_id)
            )
            return {row[0]: row[1] for row in result.all()}
