from typing import Optional
from uuid import UUID

from src.application.farm.models import CropMaster
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import SeedLot
from .repository import SeedLotRepository
from .schemas import (
    SeedLotAddResult,
    SeedLotAdjust,
    SeedLotAdjustResult,
    SeedLotCreate,
    SeedLotMerge,
    SeedLotRead,
    SeedLotSort,
    SeedLotTagging,
    SeedLotUpdate,
    SeedTagCount,
)
from .units import as_seeds, convert, effective_tsw, equivalent, normalize_tags, normalize_unit


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


def _tsw(lot: SeedLot, crop: CropMaster) -> Optional[float]:
    return effective_tsw(lot.thousand_seed_weight_g, crop.thousand_seed_weight_g)


def _read(lot: SeedLot, crop: CropMaster, cls=SeedLotRead, **extra) -> SeedLotRead:
    tsw = _tsw(lot, crop)
    eq_qty, eq_unit = equivalent(lot.quantity, lot.unit, tsw)
    return cls.model_validate(
        {
            **{c.name: getattr(lot, c.name) for c in SeedLot.__table__.columns if c.name != "deleted_at"},
            "tags": list(lot.tags or []),
            "crop_name": crop.name,
            "crop_variety": crop.variety,
            "crop_family": crop.family,
            "effective_thousand_seed_weight_g": tsw,
            "equivalent_quantity": round(eq_qty, 3) if eq_qty is not None else None,
            "equivalent_unit": eq_unit,
            **extra,
        }
    )


def _sort_key(sort: SeedLotSort):
    if sort == "quantity":
        # Biggest stock first, comparable across units when the seed weight is known.
        def key(pair):
            lot, crop = pair
            seeds = as_seeds(lot.quantity, lot.unit, _tsw(lot, crop))
            return (seeds is None, -(seeds if seeds is not None else lot.quantity))
        return key
    if sort == "recent":
        return lambda pair: -pair[0].created_at.timestamp()  # newest loaded first; edits don't reorder
    if sort == "name":
        return lambda pair: (
            pair[1].name.lower(), (pair[1].variety or "").lower(), (pair[0].variety_note or "").lower()
        )
    return None  # "expiry": the repository's order


class InventoryService:
    def __init__(self, repository: SeedLotRepository, farm_service=None):
        self.repo = repository
        self.farm = farm_service

    async def list_seed_lots(
        self,
        actor: Actor,
        crop_master_id: Optional[UUID] = None,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
        in_stock: Optional[bool] = None,
        sort: SeedLotSort = "expiry",
    ) -> list[SeedLotRead]:
        rows = await self.repo.list(
            actor.account_id, crop_master_id=crop_master_id, query=query or None,
            tags=normalize_tags(tags) or None, in_stock=in_stock,
        )
        key = _sort_key(sort)
        if key:
            rows = sorted(rows, key=key)
        return [_read(lot, crop) for lot, crop in rows]

    async def get_seed_lot(self, actor: Actor, lot_id: UUID) -> SeedLotRead:
        row = await self.repo.get(actor.account_id, lot_id)
        if row is None:
            raise NotFoundError(f"Seed lot {lot_id} not found.")
        return _read(*row)

    async def find_matching_lot(
        self, actor: Actor, crop_master_id: UUID, variety_note: Optional[str] = None
    ) -> Optional[SeedLotRead]:
        row = await self.repo.find_matching(actor.account_id, crop_master_id, variety_note)
        return _read(*row) if row else None

    async def seed_tags(self, actor: Actor) -> list[SeedTagCount]:
        return [SeedTagCount(tag=t, count=n) for t, n in await self.repo.tag_counts(actor.account_id)]

    async def add_seed_lot(self, actor: Actor, data: SeedLotCreate) -> SeedLotAddResult:
        _require_manager(actor)
        if self.farm is not None:
            await self.farm.get_crop_master(actor, data.crop_master_id)
        existing = await self.repo.find_matching(actor.account_id, data.crop_master_id, data.variety_note)
        if existing and data.merge_into_existing:
            lot, _ = existing

            def merge_in(lot: SeedLot, crop: CropMaster) -> None:
                if data.thousand_seed_weight_g and not lot.thousand_seed_weight_g:
                    lot.thousand_seed_weight_g = data.thousand_seed_weight_g
                tsw = effective_tsw(data.thousand_seed_weight_g, _tsw(lot, crop))
                lot.quantity = lot.quantity + convert(data.quantity, data.unit, lot.unit, tsw)
                lot.tags = normalize_tags([*(lot.tags or []), *data.tags])
                for name in ("expiry_date", "acquired_date", "source", "notes"):
                    if getattr(lot, name) is None and getattr(data, name) is not None:
                        setattr(lot, name, getattr(data, name))
                if data.expiry_date and lot.expiry_date and data.expiry_date < lot.expiry_date:
                    lot.expiry_date = data.expiry_date  # the stock now expires with its earliest part

            result = await self.repo.apply(actor.account_id, lot.id, merge_in)
            if result is None:
                raise NotFoundError(f"Seed lot {lot.id} not found.")
            return _read(result[0], result[1], SeedLotAddResult, merged=True)

        values = data.model_dump(exclude={"merge_into_existing"})
        lot = await self.repo.create(SeedLot(account_id=actor.account_id, **values))
        row = await self.repo.get(actor.account_id, lot.id)
        return _read(*row, cls=SeedLotAddResult, duplicate_of=existing[0].id if existing else None)

    async def update_seed_lot(self, actor: Actor, lot_id: UUID, data: SeedLotUpdate) -> SeedLotRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        if values.get("crop_master_id") is None:
            values.pop("crop_master_id", None)
        elif self.farm is not None:
            await self.farm.get_crop_master(actor, values["crop_master_id"])
        if "tags" in values and values["tags"] is None:
            values["tags"] = []
        if "unit" in values and values["unit"] is None:
            values.pop("unit")

        def change(lot: SeedLot, crop: CropMaster) -> None:
            new_unit = values.pop("unit", None)
            for key, value in values.items():
                setattr(lot, key, value)
            if new_unit and new_unit != lot.unit:
                # Same stock, other unit: a lot weighed in grams becomes counted, or the reverse.
                lot.quantity = convert(lot.quantity, lot.unit, new_unit, _tsw(lot, crop))
                lot.unit = new_unit

        result = await self.repo.apply(actor.account_id, lot_id, change)
        if result is None:
            raise NotFoundError(f"Seed lot {lot_id} not found.")
        lot, crop, _ = result
        if "crop_master_id" in values and crop.id != lot.crop_master_id:
            return await self.get_seed_lot(actor, lot_id)
        return _read(lot, crop)

    async def adjust_seed_lot(self, actor: Actor, lot_id: UUID, data: SeedLotAdjust) -> SeedLotAdjustResult:
        """Add, subtract or set the stock, in seeds or grams (converted to the lot's own unit)."""
        if data.op != "subtract":
            _require_manager(actor)  # consuming after sowing is open to staff; restocking/correcting isn't
        if data.op != "set" and data.amount <= 0:
            raise InvalidInputError("amount must be positive.")
        unit = data.unit and (normalize_unit(data.unit) or data.unit)

        def apply(lot: SeedLot, crop: CropMaster) -> tuple[float, bool]:
            if data.thousand_seed_weight_g:
                lot.thousand_seed_weight_g = data.thousand_seed_weight_g
            amount = convert(data.amount, unit or lot.unit, lot.unit, _tsw(lot, crop))
            if data.op == "add":
                lot.quantity = lot.quantity + amount
                return amount, False
            if data.op == "set":
                lot.quantity = amount
                return amount, False
            clamped = amount > lot.quantity + 1e-9
            taken = min(amount, lot.quantity)
            lot.quantity = max(0.0, lot.quantity - amount)
            return taken, clamped

        result = await self.repo.apply(actor.account_id, lot_id, apply)
        if result is None:
            raise NotFoundError(f"Seed lot {lot_id} not found.")
        lot, crop, (applied, clamped) = result
        return _read(lot, crop, SeedLotAdjustResult, applied_amount=round(applied, 6), clamped=clamped)

    async def consume_seed_lot(
        self, actor: Actor, lot_id: UUID, quantity: float, unit: Optional[str] = None
    ) -> SeedLotAdjustResult:
        if quantity <= 0:
            raise InvalidInputError("quantity must be positive.")
        # A free-text unit (e.g. an old sowing in "plantines") is taken as the lot's own, as before.
        return await self.adjust_seed_lot(
            actor, lot_id, SeedLotAdjust(op="subtract", amount=quantity, unit=normalize_unit(unit))
        )

    async def merge_seed_lots(self, actor: Actor, data: SeedLotMerge) -> SeedLotRead:
        """Fold several lots into one: quantities converted to the target's unit, tags and notes joined,
        planned sowings re-pointed, the sources deleted."""
        _require_manager(actor)
        source_ids = [i for i in dict.fromkeys(data.source_ids) if i != data.target_id]
        if not source_ids:
            raise InvalidInputError("Pick at least one lot other than the target to merge.")
        target = await self.repo.get(actor.account_id, data.target_id)
        if target is None:
            raise NotFoundError(f"Seed lot {data.target_id} not found.")
        lot, crop = target
        sources = []
        for sid in source_ids:
            row = await self.repo.get(actor.account_id, sid)
            if row is None:
                raise NotFoundError(f"Seed lot {sid} not found.")
            sources.append(row)

        quantity, tags = lot.quantity, list(lot.tags or [])
        tsw_target = _tsw(lot, crop)
        notes = [lot.notes] if lot.notes else []
        expiry = lot.expiry_date
        for src, src_crop in sources:
            quantity += convert(src.quantity, src.unit, lot.unit, _tsw(src, src_crop) or tsw_target)
            tags += list(src.tags or [])
            if src.notes and src.notes not in notes:
                notes.append(src.notes)
            if src.expiry_date and (expiry is None or src.expiry_date < expiry):
                expiry = src.expiry_date
        values = {
            "quantity": quantity,
            "tags": normalize_tags(tags),
            "notes": "\n".join(notes) or None,
            "expiry_date": expiry,
        }
        merged = await self.repo.merge(actor.account_id, lot.id, source_ids, values)
        if merged is None:
            raise NotFoundError(f"Seed lot {data.target_id} not found.")
        return _read(merged, crop)

    async def tag_seed_lots(self, actor: Actor, data: SeedLotTagging) -> list[SeedLotRead]:
        _require_manager(actor)
        if not data.add and not data.remove:
            raise InvalidInputError("Nothing to add or remove.")
        lot_ids = list(dict.fromkeys(data.lot_ids))
        for lot_id in lot_ids:  # all or nothing: check every lot before touching any
            if await self.repo.get(actor.account_id, lot_id) is None:
                raise NotFoundError(f"Seed lot {lot_id} not found.")
        out = []
        for lot_id in lot_ids:
            def retag(lot: SeedLot, _crop: CropMaster) -> None:
                lot.tags = [t for t in normalize_tags([*(lot.tags or []), *data.add]) if t not in data.remove]

            result = await self.repo.apply(actor.account_id, lot_id, retag)
            if result is None:
                raise NotFoundError(f"Seed lot {lot_id} not found.")
            out.append(_read(result[0], result[1]))
        return out

    async def delete_seed_lot(self, actor: Actor, lot_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete(actor.account_id, lot_id):
            raise NotFoundError(f"Seed lot {lot_id} not found.")
