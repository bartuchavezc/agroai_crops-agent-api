"""
Farm data access. Every query takes account_id; nothing here is reachable across accounts.
"""
import json
from datetime import datetime
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import Text, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import ACTIVE_LOT_STATUSES, CropMaster, EventLot, Field, FieldEvent, FieldZone, Lot, LotZone


def _like_escape(text: str) -> str:
    """`text` as a literal inside a LIKE pattern (escape character: backslash)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def json_escape(text: str) -> str:
    """`text` as it appears between the quotes of a JSON string (jsonb cast to text keeps non-ASCII characters)."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


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
            like = f"%{_like_escape(query)}%"
            stmt = stmt.where(or_(
                CropMaster.name.ilike(like, escape="\\"), CropMaster.variety.ilike(like, escape="\\"),
                cast(CropMaster.i18n, Text).ilike(like, escape="\\"),
            ))
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
        # The neutral name, or what the crop is called in another country (i18n: {"es-MX": "Jitomate"}).
        alias = cast(CropMaster.i18n, Text).ilike(f'%"{_like_escape(json_escape(name))}"%', escape="\\")
        stmt = select(CropMaster).where(
            self._visible_crop_masters(account_id), or_(func.lower(CropMaster.name) == name.lower(), alias)
        )
        if variety:
            stmt = stmt.where(CropMaster.variety.ilike(f"%{_like_escape(variety)}%", escape="\\"))
        # The exact neutral name first, then account-specific entries over global ones.
        stmt = stmt.order_by(
            func.lower(CropMaster.name) != name.lower(), CropMaster.account_id.is_(None), CropMaster.variety
        )
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_crop_master(self, crop_master: CropMaster) -> CropMaster:
        return await self._add(crop_master)

    async def delete_crop_master(self, account_id: UUID, crop_master_id: UUID) -> bool:
        return await self._delete(CropMaster, crop_master_id, account_id)

    # ---------- zones ----------

    async def list_zones(self, account_id: UUID, field_id: Optional[UUID] = None) -> Sequence[FieldZone]:
        stmt = select(FieldZone).where(FieldZone.account_id == account_id, FieldZone.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(FieldZone.field_id == field_id)
        stmt = stmt.order_by(FieldZone.field_id, FieldZone.type, FieldZone.number)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_zone(self, account_id: UUID, zone_id: UUID) -> Optional[FieldZone]:
        return await self._get(FieldZone, zone_id, account_id)

    async def next_zone_number(self, field_id: UUID, zone_type: str) -> int:
        async with self.session_factory() as session:
            current = (
                await session.execute(
                    select(func.max(FieldZone.number)).where(
                        FieldZone.field_id == field_id, FieldZone.type == zone_type, FieldZone.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
        return (current or 0) + 1

    async def renumber_zones(self, account_id: UUID, numbers: dict[UUID, int]) -> None:
        async with self.session_factory() as session:
            for zone_id, number in numbers.items():
                await session.execute(
                    update(FieldZone)
                    .where(FieldZone.id == zone_id, FieldZone.account_id == account_id)
                    .values(number=number, updated_at=func.now())
                )
            await session.commit()

    async def zone_number_taken(
        self, field_id: UUID, zone_type: str, number: int, exclude_id: Optional[UUID] = None
    ) -> bool:
        stmt = select(FieldZone.id).where(
            FieldZone.field_id == field_id,
            FieldZone.type == zone_type,
            FieldZone.number == number,
            FieldZone.deleted_at.is_(None),
        )
        if exclude_id:
            stmt = stmt.where(FieldZone.id != exclude_id)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).first() is not None

    async def create_zone(self, zone: FieldZone) -> FieldZone:
        return await self._add(zone)

    async def update_zone(self, account_id: UUID, zone_id: UUID, values: dict) -> Optional[FieldZone]:
        return await self._update(FieldZone, zone_id, account_id, values)

    async def delete_zone(self, account_id: UUID, zone_id: UUID) -> bool:
        """Soft-deletes the zone; its lots stay in the field, just without that zone."""
        deleted = await self._soft_delete(FieldZone, zone_id, account_id)
        if deleted:
            async with self.session_factory() as session:
                await session.execute(delete(LotZone).where(LotZone.zone_id == zone_id))
                await session.commit()
        return deleted

    # ---------- lots ----------

    async def list_lots(
        self,
        account_id: UUID,
        field_id: Optional[UUID] = None,
        statuses: Optional[Iterable[str]] = None,
        zone_id: Optional[UUID] = None,
    ) -> Sequence[Lot]:
        stmt = select(Lot).where(Lot.account_id == account_id, Lot.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(Lot.field_id == field_id)
        if zone_id:
            stmt = stmt.where(Lot.id.in_(select(LotZone.lot_id).where(LotZone.zone_id == zone_id)))
        if statuses:
            stmt = stmt.where(Lot.status.in_(list(statuses)))
        stmt = stmt.order_by(Lot.planting_date.desc().nulls_last(), Lot.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_lot(self, account_id: UUID, cycle_id: UUID) -> Optional[Lot]:
        return await self._get(Lot, cycle_id, account_id)

    async def create_lot(self, lot: Lot, zone_ids: Sequence[UUID] = ()) -> Lot:
        async with self.session_factory() as session:
            session.add(lot)
            await session.flush()
            session.add_all(LotZone(lot_id=lot.id, zone_id=z, position=i) for i, z in enumerate(zone_ids))
            await session.commit()
            await session.refresh(lot)
        return lot

    async def update_lot(
        self, account_id: UUID, lot_id: UUID, values: dict, zone_ids: Optional[Sequence[UUID]] = None
    ) -> Optional[Lot]:
        lot = await self._update(Lot, lot_id, account_id, values)
        if lot is not None and zone_ids is not None:
            async with self.session_factory() as session:
                await session.execute(delete(LotZone).where(LotZone.lot_id == lot_id))
                session.add_all(LotZone(lot_id=lot_id, zone_id=z, position=i) for i, z in enumerate(zone_ids))
                await session.commit()
        return lot

    async def lot_zone_ids(self, lot_ids: Iterable[UUID]) -> dict[UUID, list[UUID]]:
        """Each lot's zones, the naming one first (only zones still in use)."""
        ids = list(lot_ids)
        if not ids:
            return {}
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(LotZone.lot_id, LotZone.zone_id)
                    .join(FieldZone, FieldZone.id == LotZone.zone_id)
                    .where(LotZone.lot_id.in_(ids), FieldZone.deleted_at.is_(None))
                    .order_by(LotZone.lot_id, LotZone.position)
                )
            ).all()
        out: dict[UUID, list[UUID]] = {i: [] for i in ids}
        for lot_id, zone_id in rows:
            out[lot_id].append(zone_id)
        return out

    async def lot_count_events(self, lot_ids: Iterable[UUID]) -> dict[UUID, list[FieldEvent]]:
        """Each lot's losses and confirmed counts (an inspection with data.count), oldest first: what its live
        quantity is computed from."""
        ids = list(lot_ids)
        if not ids:
            return {}
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(EventLot.lot_id, FieldEvent)
                    .join(FieldEvent, FieldEvent.id == EventLot.event_id)
                    .where(
                        EventLot.lot_id.in_(ids),
                        FieldEvent.outcome == "done",
                        or_(FieldEvent.type == "loss", FieldEvent.data.has_key("count")),
                    )
                    .order_by(FieldEvent.occurred_at, FieldEvent.created_at)
                )
            ).all()
        out: dict[UUID, list[FieldEvent]] = {i: [] for i in ids}
        for lot_id, event in rows:
            out[lot_id].append(event)
        return out

    async def resowings_of(self, lot_ids: Iterable[UUID]) -> dict[UUID, list[UUID]]:
        ids = list(lot_ids)
        if not ids:
            return {}
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Lot.replaces_lot_id, Lot.id)
                    .where(Lot.replaces_lot_id.in_(ids), Lot.deleted_at.is_(None))
                    .order_by(Lot.created_at)
                )
            ).all()
        out: dict[UUID, list[UUID]] = {i: [] for i in ids}
        for replaced, lot_id in rows:
            out[replaced].append(lot_id)
        return out

    async def delete_lot(self, account_id: UUID, cycle_id: UUID) -> bool:
        return await self._soft_delete(Lot, cycle_id, account_id)

    async def active_lots_with_crop(self, account_id: UUID) -> list[tuple[Lot, CropMaster]]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(Lot, CropMaster)
                .join(CropMaster, CropMaster.id == Lot.crop_master_id)
                .where(
                    Lot.account_id == account_id,
                    Lot.deleted_at.is_(None),
                    Lot.status.in_(ACTIVE_LOT_STATUSES),
                )
                .order_by(Lot.planting_date.desc().nulls_last())
            )
            return [(row[0], row[1]) for row in result.all()]

    async def used_crop_families(self, account_id: UUID) -> set[str]:
        """Botanical families the account has ever grown (any cycle status), for knowledge-module selection."""
        async with self.session_factory() as session:
            result = await session.execute(
                select(CropMaster.family)
                .join(Lot, Lot.crop_master_id == CropMaster.id)
                .where(
                    Lot.account_id == account_id,
                    Lot.deleted_at.is_(None),
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
        lot_id: Optional[UUID] = None,
        event_type: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        zone_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
    ) -> Sequence[FieldEvent]:
        stmt = select(FieldEvent).where(FieldEvent.account_id == account_id)
        if field_id:
            stmt = stmt.where(FieldEvent.field_id == field_id)
        if zone_id:
            stmt = stmt.where(FieldEvent.zone_id == zone_id)
        if before:  # paging back in time: the next page starts after the oldest `occurred_at` already received
            stmt = stmt.where(FieldEvent.occurred_at < before)
        if lot_id:
            stmt = stmt.where(FieldEvent.id.in_(select(EventLot.event_id).where(EventLot.lot_id == lot_id)))
        if event_type:
            stmt = stmt.where(FieldEvent.type == event_type)
        if since:
            stmt = stmt.where(FieldEvent.occurred_at >= since)
        if until:
            stmt = stmt.where(FieldEvent.occurred_at <= until)
        stmt = stmt.order_by(FieldEvent.occurred_at.desc(), FieldEvent.id.desc()).limit(limit)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def get_event(self, account_id: UUID, event_id: UUID) -> Optional[FieldEvent]:
        return await self._get(FieldEvent, event_id, account_id)

    async def create_event(self, event: FieldEvent, lot_ids: Sequence[UUID] = ()) -> FieldEvent:
        async with self.session_factory() as session:
            session.add(event)
            await session.flush()
            session.add_all(EventLot(event_id=event.id, lot_id=lot_id) for lot_id in lot_ids)
            await session.commit()
            await session.refresh(event)
        return event

    async def update_event(
        self, account_id: UUID, event_id: UUID, values: dict, lot_ids: Optional[Sequence[UUID]] = None
    ) -> Optional[FieldEvent]:
        event = await self._update(FieldEvent, event_id, account_id, values)
        if event is not None and lot_ids is not None:
            async with self.session_factory() as session:
                await session.execute(delete(EventLot).where(EventLot.event_id == event_id))
                session.add_all(EventLot(event_id=event_id, lot_id=lot_id) for lot_id in lot_ids)
                await session.commit()
        return event

    async def event_lot_ids(self, event_ids: Iterable[UUID]) -> dict[UUID, list[UUID]]:
        ids = list(event_ids)
        if not ids:
            return {}
        async with self.session_factory() as session:
            rows = (
                await session.execute(select(EventLot.event_id, EventLot.lot_id).where(EventLot.event_id.in_(ids)))
            ).all()
        out: dict[UUID, list[UUID]] = {i: [] for i in ids}
        for event_id, lot_id in rows:
            out[event_id].append(lot_id)
        return out

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
