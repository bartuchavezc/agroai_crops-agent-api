"""Seed inventory tools: so create_crop_cycle can draw from real stock, not an abstract catalog."""
from datetime import date
from typing import Optional
from uuid import UUID

from src.application.inventory.schemas import SeedLotCreate

from .context import ToolDeps, TurnContext, compact, tool


def inventory_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_seed_inventory(crop_master_id: Optional[str] = None) -> dict:
        """Seeds on hand (account-wide, not per field): quantity, unit, expiry. Use before suggesting what
        to sow, and to warn about lots close to expiry."""
        lots = await deps.inventory.list_seed_lots(
            ctx.actor, crop_master_id=UUID(crop_master_id) if crop_master_id else None
        )
        return {"seed_lots": compact(lots)}

    @tool
    async def consume_seed_lot(lot_id: str, quantity: float) -> dict:
        """Discount `quantity` from a seed lot (e.g. after sowing). Use the id from list_seed_inventory."""
        lot = await deps.inventory.consume_seed_lot(ctx.actor, UUID(lot_id), quantity)
        return {"updated_lot": compact(lot)}

    return [list_seed_inventory, consume_seed_lot]


def inventory_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def add_seed_lot(
        crop_master_id: str,
        quantity: float,
        unit: str = "semillas",
        variety_note: Optional[str] = None,
        acquired_date: Optional[str] = None,
        expiry_date: Optional[str] = None,
        source: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Register seeds acquired/on hand. crop_master_id from find_crop_in_catalog. Dates YYYY-MM-DD."""
        lot = await deps.inventory.add_seed_lot(
            ctx.actor,
            SeedLotCreate(
                crop_master_id=UUID(crop_master_id),
                quantity=quantity,
                unit=unit,
                variety_note=variety_note,
                acquired_date=date.fromisoformat(acquired_date) if acquired_date else None,
                expiry_date=date.fromisoformat(expiry_date) if expiry_date else None,
                source=source,
                notes=notes,
            ),
        )
        return {"created_lot": compact(lot)}

    return [add_seed_lot]
