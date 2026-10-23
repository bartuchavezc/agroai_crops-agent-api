"""Stock of inputs: items written as on their label, and an append-only ledger of receipts, consumptions (by the
applications that used them) and adjustments. The item's quantity moves only with a movement, in the same
transaction, so it always equals the sum of its ledger."""
from datetime import date, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.products.service import ProductRegistryService
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import SupplyItem, SupplyMovement
from .schemas import (
    SupplyItemCreate,
    SupplyItemRead,
    SupplyItemUpdate,
    SupplyMovementCreate,
    SupplyMovementRead,
)
from .units import convert, normalize


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


class SupplyService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], registry: ProductRegistryService):
        self.session_factory = session_factory
        self.registry = registry

    async def _item(self, session: AsyncSession, actor: Actor, item_id: UUID) -> SupplyItem:
        item = await session.get(SupplyItem, item_id)
        if item is None or item.account_id != actor.account_id or item.deleted_at is not None:
            raise NotFoundError(f"Supply {item_id} not found.")
        return item

    async def list_items(
        self,
        actor: Actor,
        query: Optional[str] = None,
        kind: Optional[str] = None,
        in_stock: Optional[bool] = None,
        expiring_within_days: Optional[int] = None,
    ) -> list[SupplyItemRead]:
        stmt = select(SupplyItem).where(SupplyItem.account_id == actor.account_id, SupplyItem.deleted_at.is_(None))
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(or_(
                SupplyItem.name.ilike(like), SupplyItem.active_ingredients.ilike(like),
                SupplyItem.registry_number.ilike(like), SupplyItem.company.ilike(like),
            ))
        if kind:
            stmt = stmt.where(SupplyItem.kind == kind)
        if in_stock is True:
            stmt = stmt.where(SupplyItem.quantity > 0)
        elif in_stock is False:
            stmt = stmt.where(SupplyItem.quantity <= 0)
        if expiring_within_days is not None:
            stmt = stmt.where(SupplyItem.expiry_date <= date.today() + timedelta(days=expiring_within_days))
        stmt = stmt.order_by(SupplyItem.name, SupplyItem.expiry_date.asc().nulls_last())
        async with self.session_factory() as session:
            return [SupplyItemRead.model_validate(i) for i in (await session.execute(stmt)).scalars()]

    async def get_item(self, actor: Actor, item_id: UUID) -> SupplyItemRead:
        async with self.session_factory() as session:
            return SupplyItemRead.model_validate(await self._item(session, actor, item_id))

    async def create_item(self, actor: Actor, data: SupplyItemCreate) -> SupplyItemRead:
        """Any member records what came in (the remito is theirs to hand); the first quantity is a receipt."""
        unit = normalize(data.unit)
        if unit is None:
            raise InvalidInputError(f"Unknown unit '{data.unit}'. Use L, ml, kg, g or unidad.")
        verified = await self.registry.verify(data.name, data.registry_number, actor.country)
        values = data.model_dump(exclude={"quantity", "unit", "image_identifier"})
        async with self.session_factory() as session:
            item = SupplyItem(
                account_id=actor.account_id, unit=unit, quantity=0.0, registry_verified=verified,
                created_by=actor.user_id, **values,
            )
            session.add(item)
            await session.flush()
            if data.quantity:
                self._move(session, actor, item, "receipt", data.quantity, reason="Ingreso inicial",
                           image_identifier=data.image_identifier)
            await session.commit()
            await session.refresh(item)
            return SupplyItemRead.model_validate(item)

    async def update_item(self, actor: Actor, item_id: UUID, data: SupplyItemUpdate) -> SupplyItemRead:
        _require_manager(actor)
        async with self.session_factory() as session:
            item = await self._item(session, actor, item_id)
            values = data.model_dump(exclude_unset=True)
            for key, value in values.items():
                setattr(item, key, value)
            if "name" in values or "registry_number" in values:
                item.registry_verified = await self.registry.verify(item.name, item.registry_number, actor.country)
            await session.commit()
            await session.refresh(item)
            return SupplyItemRead.model_validate(item)

    async def delete_item(self, actor: Actor, item_id: UUID) -> None:
        """Hidden from stock; its ledger and the applications that used it keep their text."""
        _require_manager(actor)
        async with self.session_factory() as session:
            item = await self._item(session, actor, item_id)
            item.deleted_at = utcnow()
            await session.commit()

    def _move(
        self, session: AsyncSession, actor: Actor, item: SupplyItem, kind: str, quantity: float,
        reason: Optional[str] = None, application_id: Optional[UUID] = None, occurred_at=None,
        image_identifier: Optional[str] = None,
    ) -> SupplyMovement:
        movement = SupplyMovement(
            account_id=actor.account_id, item_id=item.id, kind=kind, quantity=round(quantity, 6), reason=reason,
            application_id=application_id, occurred_at=occurred_at or utcnow(), image_identifier=image_identifier,
            user_id=actor.user_id,
        )
        session.add(movement)
        item.quantity = round((item.quantity or 0.0) + quantity, 6)
        return movement

    async def add_movement(self, actor: Actor, item_id: UUID, data: SupplyMovementCreate) -> SupplyItemRead:
        if data.kind == "adjustment":
            _require_manager(actor)
            if not (data.reason or "").strip():
                raise InvalidInputError("An adjustment needs its reason (e.g. 'conteo: había 2 L, no 3').")
        elif data.quantity <= 0:
            raise InvalidInputError("A receipt adds a positive quantity.")
        async with self.session_factory() as session:
            item = await self._item(session, actor, item_id)
            amount = convert(data.quantity, data.unit, item.unit) if data.unit else data.quantity
            self._move(session, actor, item, data.kind, amount, reason=data.reason, occurred_at=data.occurred_at,
                       image_identifier=data.image_identifier)
            await session.commit()
            await session.refresh(item)
            return SupplyItemRead.model_validate(item)

    async def movements(self, actor: Actor, item_id: UUID, limit: int = 100) -> list[SupplyMovementRead]:
        async with self.session_factory() as session:
            await self._item(session, actor, item_id)
            rows = (await session.execute(
                select(SupplyMovement).where(SupplyMovement.item_id == item_id)
                .order_by(SupplyMovement.occurred_at.desc(), SupplyMovement.created_at.desc())
                .limit(max(1, min(limit, 500)))
            )).scalars()
            return [SupplyMovementRead.model_validate(m) for m in rows]

    async def consume_for_application(
        self, session: AsyncSession, actor: Actor, item_id: UUID, quantity: float, unit: str, application_id: UUID,
        reason: str,
    ) -> SupplyItem:
        """Inside the application's own transaction: what a confirmed application used, in the item's unit. A
        negative quantity gives it back (a corrected or voided application). Stock may go below zero — the record
        of what was applied wins over a stock that wasn't loaded right."""
        item = await self._item(session, actor, item_id)
        amount = convert(quantity, unit, item.unit)
        self._move(session, actor, item, "consumption" if amount > 0 else "adjustment", -amount, reason=reason,
                   application_id=application_id)
        return item

    async def item_in_session(self, session: AsyncSession, actor: Actor, item_id: UUID) -> SupplyItem:
        return await self._item(session, actor, item_id)
