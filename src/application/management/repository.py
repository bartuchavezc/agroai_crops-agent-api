from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import BudgetEntry, RoadmapItem, ShoppingListItem


class ManagementRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    # ---------- shopping list ----------

    async def list_shopping_items(
        self, account_id: UUID, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> Sequence[ShoppingListItem]:
        stmt = select(ShoppingListItem).where(
            ShoppingListItem.account_id == account_id, ShoppingListItem.deleted_at.is_(None)
        )
        if field_id:
            stmt = stmt.where(ShoppingListItem.field_id == field_id)
        if status:
            stmt = stmt.where(ShoppingListItem.status == status)
        stmt = stmt.order_by(ShoppingListItem.status, ShoppingListItem.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_shopping_item(self, item: ShoppingListItem) -> ShoppingListItem:
        async with self.session_factory() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
        return item

    async def update_shopping_item(self, account_id: UUID, item_id: UUID, values: dict) -> Optional[ShoppingListItem]:
        async with self.session_factory() as session:
            item = (
                await session.execute(
                    select(ShoppingListItem).where(
                        ShoppingListItem.id == item_id, ShoppingListItem.account_id == account_id,
                        ShoppingListItem.deleted_at.is_(None),
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

    async def delete_shopping_item(self, account_id: UUID, item_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(ShoppingListItem)
                .where(
                    ShoppingListItem.id == item_id, ShoppingListItem.account_id == account_id,
                    ShoppingListItem.deleted_at.is_(None),
                )
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0

    # ---------- budget ----------

    async def list_budget_entries(
        self, account_id: UUID, field_id: Optional[UUID] = None,
        since: Optional[str] = None, until: Optional[str] = None,
    ) -> Sequence[BudgetEntry]:
        stmt = select(BudgetEntry).where(BudgetEntry.account_id == account_id, BudgetEntry.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(BudgetEntry.field_id == field_id)
        if since:
            stmt = stmt.where(BudgetEntry.date >= since)
        if until:
            stmt = stmt.where(BudgetEntry.date <= until)
        stmt = stmt.order_by(BudgetEntry.date.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_budget_entry(self, entry: BudgetEntry) -> BudgetEntry:
        async with self.session_factory() as session:
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
        return entry

    async def delete_budget_entry(self, account_id: UUID, entry_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(BudgetEntry)
                .where(
                    BudgetEntry.id == entry_id, BudgetEntry.account_id == account_id,
                    BudgetEntry.deleted_at.is_(None),
                )
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0

    # ---------- roadmap ----------

    async def list_roadmap_items(
        self, account_id: UUID, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> Sequence[RoadmapItem]:
        stmt = select(RoadmapItem).where(RoadmapItem.account_id == account_id, RoadmapItem.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(RoadmapItem.field_id == field_id)
        if status:
            stmt = stmt.where(RoadmapItem.status == status)
        stmt = stmt.order_by(RoadmapItem.target_date.asc().nulls_last(), RoadmapItem.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def create_roadmap_item(self, item: RoadmapItem) -> RoadmapItem:
        async with self.session_factory() as session:
            session.add(item)
            await session.commit()
            await session.refresh(item)
        return item

    async def update_roadmap_item(self, account_id: UUID, item_id: UUID, values: dict) -> Optional[RoadmapItem]:
        async with self.session_factory() as session:
            item = (
                await session.execute(
                    select(RoadmapItem).where(
                        RoadmapItem.id == item_id, RoadmapItem.account_id == account_id,
                        RoadmapItem.deleted_at.is_(None),
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

    async def delete_roadmap_item(self, account_id: UUID, item_id: UUID) -> bool:
        async with self.session_factory() as session:
            result = await session.execute(
                update(RoadmapItem)
                .where(
                    RoadmapItem.id == item_id, RoadmapItem.account_id == account_id,
                    RoadmapItem.deleted_at.is_(None),
                )
                .values(deleted_at=func.now())
            )
            await session.commit()
        return result.rowcount > 0
