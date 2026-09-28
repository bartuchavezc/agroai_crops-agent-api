from typing import Optional
from uuid import UUID

from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import SeedLot
from .repository import SeedLotRepository
from .schemas import SeedLotCreate, SeedLotRead


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


class InventoryService:
    def __init__(self, repository: SeedLotRepository, farm_service=None):
        self.repo = repository
        self.farm = farm_service

    async def list_seed_lots(self, actor: Actor, crop_master_id: Optional[UUID] = None) -> list[SeedLotRead]:
        items = await self.repo.list(actor.account_id, crop_master_id=crop_master_id)
        return [SeedLotRead.model_validate(i) for i in items]

    async def add_seed_lot(self, actor: Actor, data: SeedLotCreate) -> SeedLotRead:
        _require_manager(actor)
        if self.farm is not None:
            await self.farm.get_crop_master(actor, data.crop_master_id)
        lot = await self.repo.create(SeedLot(account_id=actor.account_id, **data.model_dump()))
        return SeedLotRead.model_validate(lot)

    async def consume_seed_lot(self, actor: Actor, lot_id: UUID, quantity: float) -> SeedLotRead:
        if quantity <= 0:
            raise InvalidInputError("quantity must be positive.")
        lot = await self.repo.adjust_quantity(actor.account_id, lot_id, -quantity)
        if lot is None:
            raise NotFoundError(f"Seed lot {lot_id} not found.")
        return SeedLotRead.model_validate(lot)

    async def delete_seed_lot(self, actor: Actor, lot_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.delete(actor.account_id, lot_id):
            raise NotFoundError(f"Seed lot {lot_id} not found.")
