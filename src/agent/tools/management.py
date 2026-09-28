"""Management tools: shopping list, budget ledger, roadmap — the '/gestion' module, mirrored for chat."""
from datetime import date
from typing import Optional
from uuid import UUID

from src.application.management.schemas import (
    BudgetEntryCreate,
    RoadmapItemCreate,
    RoadmapItemUpdate,
    ShoppingItemCreate,
    ShoppingItemUpdate,
)

from .context import ToolDeps, TurnContext, compact, resolve_field, tool


def management_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_shopping_list(field: Optional[str] = None, status: Optional[str] = None) -> dict:
        """Shopping list items. status: pendiente|comprado."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        items = await deps.management.list_shopping_list(ctx.actor, field_id=field_id, status=status)
        return {"items": compact(items)}

    @tool
    async def add_shopping_item(
        name: str, field: Optional[str] = None, category: Optional[str] = None,
        quantity: Optional[float] = None, unit: Optional[str] = None, estimated_price: Optional[float] = None,
    ) -> dict:
        """Add an item to the shopping list (seeds, tools, inputs...)."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        item = await deps.management.add_shopping_item(
            ctx.actor,
            ShoppingItemCreate(
                name=name, field_id=field_id, category=category, quantity=quantity, unit=unit,
                estimated_price=estimated_price,
            ),
        )
        return {"created_item": compact(item)}

    @tool
    async def mark_shopping_item_bought(item_id: str) -> dict:
        """Mark a shopping list item as bought."""
        update = ShoppingItemUpdate(status="comprado")
        item = await deps.management.update_shopping_item(ctx.actor, UUID(item_id), update)
        return {"updated_item": compact(item)}

    @tool
    async def list_budget(
        field: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None
    ) -> dict:
        """Budget ledger entries (gastos/ingresos). Dates YYYY-MM-DD."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        items = await deps.management.list_budget(ctx.actor, field_id=field_id, since=since, until=until)
        return {"entries": compact(items)}

    @tool
    async def add_budget_entry(
        description: str, amount: float, type: str, entry_date: Optional[str] = None,
        field: Optional[str] = None, category: Optional[str] = None,
    ) -> dict:
        """Log an expense or income. type: gasto|ingreso. entry_date defaults to today, YYYY-MM-DD."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        entry = await deps.management.add_budget_entry(
            ctx.actor,
            BudgetEntryCreate(
                description=description, amount=amount, type=type,
                date=date.fromisoformat(entry_date) if entry_date else date.today(),
                field_id=field_id, category=category,
            ),
        )
        return {"created_entry": compact(entry)}

    @tool
    async def get_budget_summary(
        field: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None
    ) -> dict:
        """Totals (gastos/ingresos/balance) by category, for a field or the whole account. Gives real
        substance to "are we meeting our goals" — cost vs. harvest, not just plant status."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        summary = await deps.management.get_budget_summary(ctx.actor, field_id=field_id, since=since, until=until)
        return compact(summary)

    @tool
    async def list_roadmap(field: Optional[str] = None, status: Optional[str] = None) -> dict:
        """Roadmap / pending tasks and projects. status: pendiente|en_curso|hecho."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        items = await deps.management.list_roadmap(ctx.actor, field_id=field_id, status=status)
        return {"items": compact(items)}

    @tool
    async def add_roadmap_item(
        title: str, field: Optional[str] = None, description: Optional[str] = None,
        target_date: Optional[str] = None,
    ) -> dict:
        """Add a task/project to the roadmap. target_date YYYY-MM-DD, optional."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        item = await deps.management.add_roadmap_item(
            ctx.actor,
            RoadmapItemCreate(
                title=title, field_id=field_id, description=description,
                target_date=date.fromisoformat(target_date) if target_date else None,
            ),
        )
        return {"created_item": compact(item)}

    @tool
    async def update_roadmap_item(
        item_id: str, status: Optional[str] = None, target_date: Optional[str] = None
    ) -> dict:
        """Update a roadmap item's status (pendiente|en_curso|hecho) and/or target date."""
        item = await deps.management.update_roadmap_item(
            ctx.actor, UUID(item_id),
            RoadmapItemUpdate(status=status, target_date=date.fromisoformat(target_date) if target_date else None),
        )
        return {"updated_item": compact(item)}

    return [
        list_shopping_list,
        add_shopping_item,
        mark_shopping_item_bought,
        list_budget,
        add_budget_entry,
        get_budget_summary,
        list_roadmap,
        add_roadmap_item,
        update_roadmap_item,
    ]
