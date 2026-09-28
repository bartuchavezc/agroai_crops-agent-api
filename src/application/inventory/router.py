from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import SeedLotCreate, SeedLotRead
from .service import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])

INVENTORY = Provide["application.inventory_service"]


@_both(router.get, "/seed-lots", response_model=List[SeedLotRead], summary="List Seed Lots")
@inject
async def list_seed_lots(
    crop_master_id: Optional[UUID] = None,
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.list_seed_lots(actor, crop_master_id=crop_master_id)


@_both(
    router.post, "/seed-lots", response_model=SeedLotRead, status_code=status.HTTP_201_CREATED,
    summary="Add Seed Lot",
)
@inject
async def add_seed_lot(
    body: SeedLotCreate, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    return await inventory.add_seed_lot(actor, body)


@router.post("/seed-lots/{lot_id}/consume", response_model=SeedLotRead, summary="Consume Seed Lot")
@inject
async def consume_seed_lot(
    lot_id: UUID,
    quantity: float = Body(..., embed=True, gt=0),
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.consume_seed_lot(actor, lot_id, quantity)


@router.delete("/seed-lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Seed Lot")
@inject
async def delete_seed_lot(
    lot_id: UUID, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    await inventory.delete_seed_lot(actor, lot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
