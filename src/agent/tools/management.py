"""Management tools: shopping list, budget ledger, roadmap — the '/gestion' module, mirrored for chat.

Every item can be tied to a field and (shopping/roadmap) assigned to a member. Filters take a field
name and a member name/email; "ninguno" means "no field" / "unassigned"."""
from datetime import date
from typing import Optional
from uuid import UUID

from src.application.management.repository import NONE
from src.application.management.schemas import (
    BudgetEntryCreate,
    BudgetEntryUpdate,
    RoadmapItemCreate,
    RoadmapItemUpdate,
    ShoppingItemCreate,
    ShoppingItemUpdate,
)
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, parse_date, resolve_field, tool

_NONE_WORDS = {"ninguno", "ninguna", "none", "sin asignar", "sin campo"}

class _Resolvers:
    """Field and member lookups shared by both tool groups (model-provided names → ids of this account)."""

    def __init__(self, deps: ToolDeps, ctx: TurnContext):
        self.deps, self.ctx = deps, ctx

    async def field_filter(self, field: Optional[str]):
        if not field:
            return None
        if is_clear(field):
            return NONE
        return (await resolve_field(self.deps, self.ctx, field)).id

    async def field_value(self, field: Optional[str]) -> Optional[UUID]:
        """For writes: a field name/id, or None. Unlike resolve_field, never falls back to a default."""
        value = await self.field_filter(field)
        return None if value in (None, NONE) else value

    async def member_id(self, who: Optional[str]):
        """A member by id, email, or (part of) their name; "yo"/"me" is the caller; "ninguno" = NONE."""
        if not who:
            return None
        key = who.strip().lower()
        if key in _NONE_WORDS:
            return NONE
        if key in {"yo", "me", "mí", "mi"}:
            return self.ctx.actor.user_id
        members = await self.deps.management.list_members(self.ctx.actor)
        try:
            uid = UUID(who)
            if any(m.id == uid for m in members):
                return uid
        except ValueError:
            pass
        exact = [m for m in members if (m.email or "").lower() == key]
        if exact:
            return exact[0].id
        matches = [
            m for m in members
            if key in f"{m.first_name or ''} {m.last_name or ''}".lower() or key in (m.email or "").lower()
        ]
        if len(matches) == 1:
            return matches[0].id
        names = ", ".join(_member_label(m) for m in (matches or members))
        if matches:
            raise InvalidInputError(f"'{who}' matches several members: {names}. Ask which one.")
        raise InvalidInputError(f"No member matches '{who}'. Members: {names}.")

    async def member_value(self, who: Optional[str]) -> Optional[UUID]:
        value = await self.member_id(who)
        return None if value in (None, NONE) else value

    async def ref_updates(self, field: Optional[str], assigned_to: Optional[str] = None) -> dict:
        """field/assigned_to arguments of an update_ tool: omitted = unchanged, "ninguno" = clear."""
        values: dict = {}
        if field is not None:
            values["field_id"] = await self.field_value(field)
        if assigned_to is not None:
            values["assigned_to"] = await self.member_value(assigned_to)
        return values


def is_clear(value: Optional[str]) -> bool:
    return value is not None and value.strip().lower() in _NONE_WORDS


def management_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    """Every role: read, add, and update shopping/roadmap items (staff tick purchases and tasks)."""
    r = _Resolvers(deps, ctx)

    @tool
    async def list_account_members() -> dict:
        """Members of the account (to assign shopping/roadmap items to someone)."""
        members = await deps.management.list_members(ctx.actor)
        return {"members": [{"id": str(m.id), "name": _member_label(m), "role": m.role} for m in members]}

    # ---------- shopping list ----------

    @tool
    async def list_shopping_list(
        field: Optional[str] = None, status: Optional[str] = None, assigned_to: Optional[str] = None
    ) -> dict:
        """Shopping list items. status: pendiente|comprado|cancelado. field: a field name, or "ninguno" for
        items not tied to a field. assigned_to: member name/email, "yo", or "ninguno" for unassigned."""
        items = await deps.management.list_shopping_list(
            ctx.actor, field_id=await r.field_filter(field), status=status or None,
            assigned_to=await r.member_id(assigned_to),
        )
        return {"items": compact(items)}

    @tool
    async def add_shopping_item(
        name: str, field: Optional[str] = None, category: Optional[str] = None,
        quantity: Optional[float] = None, unit: Optional[str] = None, estimated_price: Optional[float] = None,
        assigned_to: Optional[str] = None,
    ) -> dict:
        """Add an item to the shopping list (seeds, tools, inputs...). field: which field it's for (omit for
        general purchases). assigned_to: who buys it (member name/email or "yo")."""
        item = await deps.management.add_shopping_item(
            ctx.actor,
            ShoppingItemCreate(
                name=name, field_id=await r.field_value(field), category=category, quantity=quantity, unit=unit,
                estimated_price=estimated_price, assigned_to=await r.member_value(assigned_to),
            ),
        )
        return {"created_item": compact(item)}

    @tool
    async def update_shopping_item(
        item_id: str, status: Optional[str] = None, name: Optional[str] = None, field: Optional[str] = None,
        category: Optional[str] = None, quantity: Optional[float] = None, unit: Optional[str] = None,
        estimated_price: Optional[float] = None, assigned_to: Optional[str] = None,
    ) -> dict:
        """Edit a shopping list item; only the arguments you pass change. status: pendiente|comprado|cancelado
        (use comprado when it was bought, cancelado when it won't be). field / assigned_to: "ninguno" clears
        them. Use list_shopping_list to find the item_id."""
        values: dict = {"status": status, "name": name, "category": category, "quantity": quantity,
                        "unit": unit, "estimated_price": estimated_price}
        values = {k: v for k, v in values.items() if v is not None}
        values.update(await r.ref_updates(field, assigned_to))
        item = await deps.management.update_shopping_item(ctx.actor, UUID(item_id), ShoppingItemUpdate(**values))
        return {"updated_item": compact(item)}

    # ---------- budget ----------

    @tool
    async def list_budget(
        field: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None,
        type: Optional[str] = None,
    ) -> dict:
        """Budget ledger entries (gastos/ingresos). Dates YYYY-MM-DD. type: gasto|ingreso. field: a field
        name, or "ninguno" for entries not tied to a field."""
        items = await deps.management.list_budget(
            ctx.actor, field_id=await r.field_filter(field), since=since, until=until, type=type or None
        )
        return {"entries": compact(items)}

    @tool
    async def add_budget_entry(
        description: str, amount: float, type: str, entry_date: Optional[str] = None,
        field: Optional[str] = None, category: Optional[str] = None,
    ) -> dict:
        """Log an expense or income. type: gasto|ingreso. entry_date defaults to today, YYYY-MM-DD. field:
        which field it belongs to (omit for general expenses)."""
        entry = await deps.management.add_budget_entry(
            ctx.actor,
            BudgetEntryCreate(
                description=description, amount=amount, type=type,
                date=parse_date(entry_date) or date.today(),
                field_id=await r.field_value(field), category=category,
            ),
        )
        return {"created_entry": compact(entry)}

    @tool
    async def get_budget_summary(
        field: Optional[str] = None, since: Optional[str] = None, until: Optional[str] = None
    ) -> dict:
        """Totals (gastos/ingresos/balance) by category, for one field ("ninguno" = entries with no field) or
        the whole account. Gives real substance to "are we meeting our goals" — cost vs. harvest."""
        summary = await deps.management.get_budget_summary(
            ctx.actor, field_id=await r.field_filter(field), since=since, until=until
        )
        return compact(summary)

    # ---------- roadmap ----------

    @tool
    async def list_roadmap(
        field: Optional[str] = None, status: Optional[str] = None, assigned_to: Optional[str] = None
    ) -> dict:
        """Roadmap / pending tasks and projects. status: pendiente|en_curso|hecho|cancelado. field: a field
        name or "ninguno". assigned_to: member name/email, "yo", or "ninguno" for unassigned."""
        items = await deps.management.list_roadmap(
            ctx.actor, field_id=await r.field_filter(field), status=status or None,
            assigned_to=await r.member_id(assigned_to),
        )
        return {"items": compact(items)}

    @tool
    async def add_roadmap_item(
        title: str, field: Optional[str] = None, description: Optional[str] = None,
        target_date: Optional[str] = None, assigned_to: Optional[str] = None,
    ) -> dict:
        """Add a task/project to the roadmap. target_date YYYY-MM-DD, optional. field: which field (omit for
        general tasks). assigned_to: who does it (member name/email or "yo")."""
        item = await deps.management.add_roadmap_item(
            ctx.actor,
            RoadmapItemCreate(
                title=title, field_id=await r.field_value(field), description=description,
                target_date=parse_date(target_date), assigned_to=await r.member_value(assigned_to),
            ),
        )
        return {"created_item": compact(item)}

    @tool
    async def update_roadmap_item(
        item_id: str, status: Optional[str] = None, title: Optional[str] = None,
        description: Optional[str] = None, target_date: Optional[str] = None, field: Optional[str] = None,
        assigned_to: Optional[str] = None,
    ) -> dict:
        """Edit a roadmap item; only the arguments you pass change. status: pendiente|en_curso|hecho|cancelado.
        field / assigned_to: "ninguno" clears them. Use list_roadmap to find the item_id."""
        values: dict = {"status": status, "title": title, "description": description,
                        "target_date": parse_date(target_date)}
        values = {k: v for k, v in values.items() if v is not None}
        values.update(await r.ref_updates(field, assigned_to))
        item = await deps.management.update_roadmap_item(ctx.actor, UUID(item_id), RoadmapItemUpdate(**values))
        return {"updated_item": compact(item)}

    return [
        list_account_members,
        list_shopping_list,
        add_shopping_item,
        update_shopping_item,
        list_budget,
        add_budget_entry,
        get_budget_summary,
        list_roadmap,
        add_roadmap_item,
        update_roadmap_item,
    ]


def management_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    """Owner/tecnico only: correcting money and deleting anything (the service enforces it too)."""
    r = _Resolvers(deps, ctx)

    @tool
    async def remove_shopping_item(item_id: str) -> dict:
        """Delete a shopping list item (soft delete: hidden from the list). If it just won't be bought,
        prefer update_shopping_item(status="cancelado") — it stays listed.
        ONLY call this after the user has explicitly confirmed in a message of their own: first restate which
        item you're about to remove, then wait for an explicit yes; never in the same turn as the first
        request."""
        await deps.management.delete_shopping_item(ctx.actor, UUID(item_id))
        return {"deleted_item_id": item_id}

    @tool
    async def update_budget_entry(
        entry_id: str, description: Optional[str] = None, amount: Optional[float] = None,
        type: Optional[str] = None, entry_date: Optional[str] = None, field: Optional[str] = None,
        category: Optional[str] = None,
    ) -> dict:
        """Correct a budget entry; only the arguments you pass change. field: "ninguno" unlinks it from its
        field. Use list_budget to find the entry_id."""
        values: dict = {"description": description, "amount": amount, "type": type,
                        "date": parse_date(entry_date), "category": category}
        values = {k: v for k, v in values.items() if v is not None}
        values.update(await r.ref_updates(field))
        entry = await deps.management.update_budget_entry(ctx.actor, UUID(entry_id), BudgetEntryUpdate(**values))
        return {"updated_entry": compact(entry)}

    @tool
    async def remove_budget_entry(entry_id: str) -> dict:
        """Delete a budget entry (soft delete: it stops counting in the balance). To fix a wrong amount or
        date, use update_budget_entry instead.
        ONLY call this after the user has explicitly confirmed in a message of their own: first restate which
        entry you're about to remove, then wait for an explicit yes; never in the same turn as the first
        request."""
        await deps.management.delete_budget_entry(ctx.actor, UUID(entry_id))
        return {"deleted_entry_id": entry_id}

    @tool
    async def remove_roadmap_item(item_id: str) -> dict:
        """Delete a roadmap item (soft delete: hidden from the roadmap). If the task just won't happen,
        prefer update_roadmap_item(status="cancelado") — it stays listed.
        ONLY call this after the user has explicitly confirmed in a message of their own: first restate which
        task you're about to remove, then wait for an explicit yes; never in the same turn as the first
        request."""
        await deps.management.delete_roadmap_item(ctx.actor, UUID(item_id))
        return {"deleted_item_id": item_id}

    return [remove_shopping_item, update_budget_entry, remove_budget_entry, remove_roadmap_item]


def _member_label(member) -> str:
    name = " ".join(p for p in (member.first_name, member.last_name) if p)
    return f"{name} <{member.email}>" if name else member.email
