from typing import Optional
from uuid import UUID

from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import BudgetEntry, RoadmapItem, ShoppingListItem
from .repository import IdFilter, ManagementRepository
from .schemas import (
    BudgetEntryCreate,
    BudgetEntryRead,
    BudgetEntryUpdate,
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
    fields/cycles/events. Read access for every role; staff can add and update shopping/roadmap items
    (they log purchases and tick tasks day to day); editing money and deleting anything is manager-only.
    Deletes are soft (deleted_at); "cancelado" is the status for things that won't happen but stay listed."""

    def __init__(self, repository: ManagementRepository, farm_service=None):
        self.repo = repository
        self.farm = farm_service

    async def _check_field(self, actor: Actor, field_id: Optional[UUID]) -> None:
        """A field_id from the client must be one of the caller's own fields (NotFound otherwise)."""
        if field_id and self.farm is not None:
            await self.farm.get_field(actor, field_id)

    async def _check_assignee(self, actor: Actor, user_id: Optional[UUID]) -> None:
        if user_id and not await self.repo.is_active_member(actor.account_id, user_id):
            raise InvalidInputError("The assignee must be an active member of the account.")

    async def _check_refs(self, actor: Actor, values: dict) -> None:
        await self._check_field(actor, values.get("field_id"))
        await self._check_assignee(actor, values.get("assigned_to"))
        if values.get("crop_cycle_id") and self.farm is not None:
            await self.farm.get_crop_cycle(actor, values["crop_cycle_id"])

    async def list_members(self, actor: Actor) -> list:
        """Active members, for assigning items (the agent resolves names/emails with this)."""
        return list(await self.repo.list_active_members(actor.account_id))

    # ---------- shopping list ----------

    async def list_shopping_list(
        self, actor: Actor, field_id: IdFilter = None, status: Optional[str] = None, assigned_to: IdFilter = None
    ) -> list[ShoppingItemRead]:
        items = await self.repo.list_shopping_items(
            actor.account_id, field_id=field_id, status=status, assigned_to=assigned_to
        )
        return [ShoppingItemRead.model_validate(i) for i in items]

    async def add_shopping_item(self, actor: Actor, data: ShoppingItemCreate) -> ShoppingItemRead:
        values = data.model_dump()
        await self._check_refs(actor, values)
        item = await self.repo.create_shopping_item(ShoppingListItem(account_id=actor.account_id, **values))
        return ShoppingItemRead.model_validate(item)

    async def update_shopping_item(self, actor: Actor, item_id: UUID, data: ShoppingItemUpdate) -> ShoppingItemRead:
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        item = await self.repo.update_shopping_item(actor.account_id, item_id, values)
        if item is None:
            raise NotFoundError(f"Shopping item {item_id} not found.")
        return ShoppingItemRead.model_validate(item)

    async def delete_shopping_item(self, actor: Actor, item_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_shopping_item(actor.account_id, item_id):
            raise NotFoundError(f"Shopping item {item_id} not found.")

    # ---------- budget ----------

    async def list_budget(
        self, actor: Actor, field_id: IdFilter = None, since: Optional[str] = None, until: Optional[str] = None,
        type: Optional[str] = None,
    ) -> list[BudgetEntryRead]:
        items = await self.repo.list_budget_entries(
            actor.account_id, field_id=field_id, since=since, until=until, type=type
        )
        return [BudgetEntryRead.model_validate(i) for i in items]

    async def add_budget_entry(self, actor: Actor, data: BudgetEntryCreate) -> BudgetEntryRead:
        values = data.model_dump()
        await self._check_refs(actor, values)
        entry = await self.repo.create_budget_entry(BudgetEntry(account_id=actor.account_id, **values))
        return BudgetEntryRead.model_validate(entry)

    async def update_budget_entry(self, actor: Actor, entry_id: UUID, data: BudgetEntryUpdate) -> BudgetEntryRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        entry = await self.repo.update_budget_entry(actor.account_id, entry_id, values)
        if entry is None:
            raise NotFoundError(f"Budget entry {entry_id} not found.")
        return BudgetEntryRead.model_validate(entry)

    async def delete_budget_entry(self, actor: Actor, entry_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_budget_entry(actor.account_id, entry_id):
            raise NotFoundError(f"Budget entry {entry_id} not found.")

    async def get_budget_summary(
        self, actor: Actor, field_id: IdFilter = None, since: Optional[str] = None, until: Optional[str] = None
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
            field_id=field_id if isinstance(field_id, UUID) else None,
            total_gastos=round(total_gastos, 2),
            total_ingresos=round(total_ingresos, 2),
            balance=round(total_ingresos - total_gastos, 2),
            by_category={k: round(v, 2) for k, v in by_category.items()},
        )

    # ---------- roadmap ----------

    async def list_roadmap(
        self, actor: Actor, field_id: IdFilter = None, status: Optional[str] = None, assigned_to: IdFilter = None
    ) -> list[RoadmapItemRead]:
        items = await self.repo.list_roadmap_items(
            actor.account_id, field_id=field_id, status=status, assigned_to=assigned_to
        )
        return [RoadmapItemRead.model_validate(i) for i in items]

    async def add_roadmap_item(self, actor: Actor, data: RoadmapItemCreate) -> RoadmapItemRead:
        values = data.model_dump()
        await self._check_refs(actor, values)
        item = await self.repo.create_roadmap_item(RoadmapItem(account_id=actor.account_id, **values))
        return RoadmapItemRead.model_validate(item)

    async def update_roadmap_item(self, actor: Actor, item_id: UUID, data: RoadmapItemUpdate) -> RoadmapItemRead:
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        item = await self.repo.update_roadmap_item(actor.account_id, item_id, values)
        if item is None:
            raise NotFoundError(f"Roadmap item {item_id} not found.")
        return RoadmapItemRead.model_validate(item)

    async def delete_roadmap_item(self, actor: Actor, item_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete_roadmap_item(actor.account_id, item_id):
            raise NotFoundError(f"Roadmap item {item_id} not found.")

