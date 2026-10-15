"""Seed inventory tools: so create_crop_cycle can draw from real stock, not an abstract catalog."""
from datetime import date
from typing import Optional
from uuid import UUID

from src.application.inventory.schemas import (
    SeedLotAdjust,
    SeedLotCreate,
    SeedLotMerge,
    SeedLotTagging,
    SeedLotUpdate,
)

from .context import ToolDeps, TurnContext, compact, tool

_WEIGHT_HINT = (
    "Lots are counted in 'semillas' or weighed in 'gramos'; thousand_seed_weight_g (grams per 1000 seeds) "
    "converts between them. If the user gives the other unit and the lot has no weight "
    "(effective_thousand_seed_weight_g missing), estimate the typical 1000-seed weight of that species/variety "
    "from agronomic knowledge, pass it as thousand_seed_weight_g and tell the user it is an estimate."
)


def _date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def inventory_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_seed_inventory(
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        in_stock: Optional[bool] = None,
        sort: str = "expiry",
        crop_master_id: Optional[str] = None,
    ) -> dict:
        """Seeds on hand (account-wide, not per field): quantity, unit, its equivalent in the other unit,
        tags, expiry. `query` searches crop, variety, family, tag and supplier; `tags` keeps lots with all of
        them; in_stock true/false; sort: expiry | quantity | recent | name. Narrow with query instead of
        listing everything. Use before suggesting what to sow, and to warn about lots close to expiry."""
        lots = await deps.inventory.list_seed_lots(
            ctx.actor,
            crop_master_id=UUID(crop_master_id) if crop_master_id else None,
            query=query,
            tags=tags,
            in_stock=in_stock,
            sort=sort if sort in ("expiry", "quantity", "recent", "name") else "expiry",
        )
        return {"seed_lots": compact(lots)}

    @tool
    async def consume_seed_lot(lot_id: str, quantity: float, unit: Optional[str] = None) -> dict:
        """Discount `quantity` from a seed lot (e.g. after sowing), in 'semillas' or 'gramos' (default: the
        lot's unit; converted with the lot's seed weight). Use the id from list_seed_inventory."""
        lot = await deps.inventory.consume_seed_lot(ctx.actor, UUID(lot_id), quantity, unit)
        return {"updated_lot": compact(lot)}

    return [list_seed_inventory, consume_seed_lot]


def inventory_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def add_seed_lot(
        crop_master_id: str,
        quantity: float,
        unit: str = "semillas",
        variety_note: Optional[str] = None,
        thousand_seed_weight_g: Optional[float] = None,
        tags: Optional[list[str]] = None,
        acquired_date: Optional[str] = None,
        expiry_date: Optional[str] = None,
        source: Optional[str] = None,
        notes: Optional[str] = None,
        merge_into_existing: bool = True,
    ) -> dict:
        """Register seeds acquired/on hand. crop_master_id from find_crop_in_catalog (add_crop_to_catalog if
        missing). unit 'semillas' or 'gramos'. tags: free labels (supplier, family, 'prueba', 'producción'…).
        Dates YYYY-MM-DD. By default, if the same crop + variety already has a lot the quantity is added to it
        (result merged=true); pass merge_into_existing=false only when the user wants a separate lot. """
        lot = await deps.inventory.add_seed_lot(
            ctx.actor,
            SeedLotCreate(
                crop_master_id=UUID(crop_master_id),
                quantity=quantity,
                unit=unit,
                variety_note=variety_note,
                thousand_seed_weight_g=thousand_seed_weight_g,
                tags=tags or [],
                acquired_date=_date(acquired_date),
                expiry_date=_date(expiry_date),
                source=source,
                notes=notes,
                merge_into_existing=merge_into_existing,
            ),
        )
        return {"seed_lot": compact(lot)}

    @tool
    async def adjust_seed_lot(
        lot_id: str,
        op: str,
        amount: float,
        unit: Optional[str] = None,
        thousand_seed_weight_g: Optional[float] = None,
    ) -> dict:
        """Change a lot's stock: op 'add' (got more), 'subtract' (used/lost), 'set' (counted it: the real
        amount; set 0 empties it). unit 'semillas' or 'gramos' (default: the lot's unit). """
        lot = await deps.inventory.adjust_seed_lot(
            ctx.actor,
            UUID(lot_id),
            SeedLotAdjust(op=op, amount=amount, unit=unit, thousand_seed_weight_g=thousand_seed_weight_g),
        )
        return {"updated_lot": compact(lot)}

    @tool
    async def update_seed_lot(
        lot_id: str,
        crop_master_id: Optional[str] = None,
        variety_note: Optional[str] = None,
        unit: Optional[str] = None,
        thousand_seed_weight_g: Optional[float] = None,
        tags: Optional[list[str]] = None,
        acquired_date: Optional[str] = None,
        expiry_date: Optional[str] = None,
        source: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Edit a seed lot; only the arguments given change. `tags` replaces all tags (to add or remove a few
        use tag_seed_lots). Changing `unit` converts the stock on hand (12 g → 4000 semillas)."""
        given = {
            "crop_master_id": UUID(crop_master_id) if crop_master_id else None,
            "variety_note": variety_note,
            "unit": unit,
            "thousand_seed_weight_g": thousand_seed_weight_g,
            "tags": tags,
            "acquired_date": _date(acquired_date),
            "expiry_date": _date(expiry_date),
            "source": source,
            "notes": notes,
        }
        data = SeedLotUpdate(**{k: v for k, v in given.items() if v is not None})
        lot = await deps.inventory.update_seed_lot(ctx.actor, UUID(lot_id), data)
        return {"updated_lot": compact(lot)}

    @tool
    async def tag_seed_lots(lot_ids: list[str], add: Optional[list[str]] = None,
                            remove: Optional[list[str]] = None) -> dict:
        """Add and/or remove tags on several lots at once, e.g. group every tomato lot under 'tomates', or
        mark a supplier. Find the lots first with list_seed_inventory(query=...)."""
        lots = await deps.inventory.tag_seed_lots(
            ctx.actor, SeedLotTagging(lot_ids=[UUID(i) for i in lot_ids], add=add or [], remove=remove or [])
        )
        return {"updated_lots": len(lots), "tags": {str(lot.id): lot.tags for lot in lots}}

    @tool
    async def merge_seed_lots(target_id: str, source_ids: list[str]) -> dict:
        """Fold duplicate lots (same seed loaded twice) into `target_id`: quantities added in the target's
        unit, tags and notes joined, earliest expiry kept, planned sowings re-pointed, sources deleted.
        Confirm with the user before merging."""
        lot = await deps.inventory.merge_seed_lots(
            ctx.actor, SeedLotMerge(target_id=UUID(target_id), source_ids=[UUID(i) for i in source_ids])
        )
        return {"merged_lot": compact(lot)}

    for fn in (add_seed_lot, adjust_seed_lot):
        fn.__doc__ = f"{fn.__doc__}{_WEIGHT_HINT}"
    return [add_seed_lot, adjust_seed_lot, update_seed_lot, tag_seed_lots, merge_seed_lots]
