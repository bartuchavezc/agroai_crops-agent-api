from typing import Optional
from uuid import UUID

from src.shared.domain.actor import Actor
from src.shared.utils.errors import NotFoundError, PermissionDeniedError

from .models import BudgetEntry, RoadmapItem, ShoppingListItem
from .repository import ManagementRepository
from .schemas import (
    BudgetEntryCreate,
    BudgetEntryRead,
    BudgetSummary,
    RoadmapItemCreate,
    RoadmapItemRead,
    RoadmapItemUpdate,
    ShoppingItemCreate,
    ShoppingItemRead,
    ShoppingItemUpdate,
)


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


class ManagementService:
    """Shopping list, budget ledger and roadmap over one repository — same pattern FarmService uses for
    fields/cycles/events. Read access for every role; write for staff too (they log purchases/expenses
    day to day), status/edit changes restricted to manager where noted."""

    def __init__(self, repository: ManagementRepository):
        self.repo = repository

    # ---------- shopping list ----------

    async def list_shopping_list(
        self, actor: Actor, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> list[ShoppingItemRead]:
        items = await self.repo.list_shopping_items(actor.account_id, field_id=field_id, status=status)
        return [ShoppingItemRead.model_validate(i) for i in items]

    async def add_shopping_item(self, actor: Actor, data: ShoppingItemCreate) -> ShoppingItemRead:
        item = await self.repo.create_shopping_item(ShoppingListItem(account_id=actor.account_id, **data.model_dump()))
        return ShoppingItemRead.model_validate(item)

    async def update_shopping_item(self, actor: Actor, item_id: UUID, data: ShoppingItemUpdate) -> ShoppingItemRead:
        item = await self.repo.update_shopping_item(actor.account_id, item_id, data.model_dump(exclude_unset=True))
        if item is None:
            raise NotFoundError(f"Shopping item {item_id} not found.")
        return ShoppingItemRead.model_validate(item)

    async def delete_shopping_item(self, actor: Actor, item_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_shopping_item(actor.account_id, item_id):
            raise NotFoundError(f"Shopping item {item_id} not found.")

    # ---------- budget ----------

    async def list_budget(
        self, actor: Actor, field_id: Optional[UUID] = None, since: Optional[str] = None, until: Optional[str] = None
    ) -> list[BudgetEntryRead]:
        items = await self.repo.list_budget_entries(actor.account_id, field_id=field_id, since=since, until=until)
        return [BudgetEntryRead.model_validate(i) for i in items]

    async def add_budget_entry(self, actor: Actor, data: BudgetEntryCreate) -> BudgetEntryRead:
        entry = await self.repo.create_budget_entry(BudgetEntry(account_id=actor.account_id, **data.model_dump()))
        return BudgetEntryRead.model_validate(entry)

    async def delete_budget_entry(self, actor: Actor, entry_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_budget_entry(actor.account_id, entry_id):
            raise NotFoundError(f"Budget entry {entry_id} not found.")

    async def get_budget_summary(
        self, actor: Actor, field_id: Optional[UUID] = None, since: Optional[str] = None, until: Optional[str] = None
    ) -> BudgetSummary:
        entries = await self.repo.list_budget_entries(actor.account_id, field_id=field_id, since=since, until=until)
        total_gastos = sum(e.amount for e in entries if e.type == "gasto")
        total_ingresos = sum(e.amount for e in entries if e.type == "ingreso")
        by_category: dict[str, float] = {}
        for e in entries:
            key = e.category or "sin categoría"
            signed = e.amount if e.type == "ingreso" else -e.amount
            by_category[key] = by_category.get(key, 0.0) + signed
        period = f"{since or '...'} a {until or 'hoy'}"
        return BudgetSummary(
            period=period,
            total_gastos=round(total_gastos, 2),
            total_ingresos=round(total_ingresos, 2),
            balance=round(total_ingresos - total_gastos, 2),
            by_category={k: round(v, 2) for k, v in by_category.items()},
        )

    # ---------- roadmap ----------

    async def list_roadmap(
        self, actor: Actor, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> list[RoadmapItemRead]:
        items = await self.repo.list_roadmap_items(actor.account_id, field_id=field_id, status=status)
        return [RoadmapItemRead.model_validate(i) for i in items]

    async def add_roadmap_item(self, actor: Actor, data: RoadmapItemCreate) -> RoadmapItemRead:
        item = await self.repo.create_roadmap_item(RoadmapItem(account_id=actor.account_id, **data.model_dump()))
        return RoadmapItemRead.model_validate(item)

    async def update_roadmap_item(self, actor: Actor, item_id: UUID, data: RoadmapItemUpdate) -> RoadmapItemRead:
        item = await self.repo.update_roadmap_item(actor.account_id, item_id, data.model_dump(exclude_unset=True))
        if item is None:
            raise NotFoundError(f"Roadmap item {item_id} not found.")
        return RoadmapItemRead.model_validate(item)

    async def delete_roadmap_item(self, actor: Actor, item_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_roadmap_item(actor.account_id, item_id):
            raise NotFoundError(f"Roadmap item {item_id} not found.")
