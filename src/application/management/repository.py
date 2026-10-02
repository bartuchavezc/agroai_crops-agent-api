from typing import Optional, Sequence, Type, TypeVar, Union
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.auth.domain.models import User

from .models import BudgetEntry, RoadmapItem, ShoppingListItem

Item = TypeVar("Item", ShoppingListItem, BudgetEntry, RoadmapItem)

# Filter sentinel: "only rows where this column is NULL" (no field / unassigned), as opposed to None = no filter.
NONE = "none"
IdFilter = Union[UUID, str, None]


def _where_id(stmt, column, value: IdFilter):
    if value == NONE:
        return stmt.where(column.is_(None))
    if value:
        return stmt.where(column == value)
    return stmt


class ManagementRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    # ---------- generic (all three tables share account_id + soft delete) ----------

    async def _create(self, item: Item) -> Item:
        async with self.session_factory() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
        return item

    async def _update(self, model: Type[Item], account_id: UUID, item_id: UUID, values: dict) -> Optional[Item]:
        async with self.session_factory() as session:
            item = (
                await session.execute(
                    select(model).where(
                        model.id == item_id, model.account_id == account_id, model.deleted_at.is_(None)
                    )
                )
            ).scalar_one_or_none()
            if item is None:
                return None
            for k, v in values.items():
                setattr(item, k, v)
            await session.commit()
            await session.refresh(item)
        return item

    async def _soft_delete(self, model: Type[Item], account_id: UUID, item_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(model)
                .where(model.id == item_id, model.account_id == account_id, model.deleted_at.is_(None))
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0

    # ---------- members (assignees) ----------

    async def list_active_members(self, account_id: UUID) -> Sequence[User]:
        stmt = (
            select(User)
            .where(User.account_id == account_id, User.is_active.is_(True))
            .order_by(User.created_at)
        )
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def is_active_member(self, account_id: UUID, user_id: UUID) -> bool:
        stmt = select(User.id).where(User.id == user_id, User.account_id == account_id, User.is_active.is_(True))
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalar_one_or_none() is not None

    # ---------- shopping list ----------

    async def list_shopping_items(
        self, account_id: UUID, field_id: IdFilter = None, status: Optional[str] = None,
        assigned_to: IdFilter = None,
    ) -> Sequence[ShoppingListItem]:
        stmt = select(ShoppingListItem).where(
            ShoppingListItem.account_id == account_id, ShoppingListItem.deleted_at.is_(None)
        )
        stmt = _where_id(stmt, ShoppingListItem.field_id, field_id)
        stmt = _where_id(stmt, ShoppingListItem.assigned_to, assigned_to)
        if status:
            stmt = stmt.where(ShoppingListItem.status == status)
        stmt = stmt.order_by(ShoppingListItem.status.desc(), ShoppingListItem.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_shopping_item(self, item: ShoppingListItem) -> ShoppingListItem:
        return await self._create(item)

    async def update_shopping_item(self, account_id: UUID, item_id: UUID, values: dict) -> Optional[ShoppingListItem]:
        return await self._update(ShoppingListItem, account_id, item_id, values)

    async def delete_shopping_item(self, account_id: UUID, item_id: UUID) -> bool:
        return await self._soft_delete(ShoppingListItem, account_id, item_id)

    # ---------- budget ----------

    async def list_budget_entries(
        self, account_id: UUID, field_id: IdFilter = None,
        since: Optional[str] = None, until: Optional[str] = None, type: Optional[str] = None,
    ) -> Sequence[BudgetEntry]:
        stmt = select(BudgetEntry).where(BudgetEntry.account_id == account_id, BudgetEntry.deleted_at.is_(None))
        stmt = _where_id(stmt, BudgetEntry.field_id, field_id)
        if since:
            stmt = stmt.where(BudgetEntry.date >= since)
        if until:
            stmt = stmt.where(BudgetEntry.date <= until)
        if type:
            stmt = stmt.where(BudgetEntry.type == type)
        stmt = stmt.order_by(BudgetEntry.date.desc(), BudgetEntry.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_budget_entry(self, entry: BudgetEntry) -> BudgetEntry:
        return await self._create(entry)

    async def update_budget_entry(self, account_id: UUID, entry_id: UUID, values: dict) -> Optional[BudgetEntry]:
        return await self._update(BudgetEntry, account_id, entry_id, values)

    async def delete_budget_entry(self, account_id: UUID, entry_id: UUID) -> bool:
        return await self._soft_delete(BudgetEntry, account_id, entry_id)

    # ---------- roadmap ----------

    async def list_roadmap_items(
        self, account_id: UUID, field_id: IdFilter = None, status: Optional[str] = None,
        assigned_to: IdFilter = None,
    ) -> Sequence[RoadmapItem]:
        stmt = select(RoadmapItem).where(RoadmapItem.account_id == account_id, RoadmapItem.deleted_at.is_(None))
        stmt = _where_id(stmt, RoadmapItem.field_id, field_id)
        stmt = _where_id(stmt, RoadmapItem.assigned_to, assigned_to)
        if status:
            stmt = stmt.where(RoadmapItem.status == status)
        stmt = stmt.order_by(RoadmapItem.target_date.asc().nulls_last(), RoadmapItem.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_roadmap_item(self, item: RoadmapItem) -> RoadmapItem:
        return await self._create(item)

    async def update_roadmap_item(self, account_id: UUID, item_id: UUID, values: dict) -> Optional[RoadmapItem]:
        return await self._update(RoadmapItem, account_id, item_id, values)

    async def delete_roadmap_item(self, account_id: UUID, item_id: UUID) -> bool:
        return await self._soft_delete(RoadmapItem, account_id, item_id)
