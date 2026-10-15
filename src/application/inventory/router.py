from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Body, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

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
from .service import InventoryService

router = APIRouter(prefix="/inventory", tags=["Inventory"])

INVENTORY = Provide["application.inventory_service"]


@_both(router.get, "/seed-lots", response_model=List[SeedLotRead], summary="List Seed Lots")
@inject
async def list_seed_lots(
    crop_master_id: Optional[UUID] = None,
    q: Optional[str] = Query(None, description="Crop, variety, family, tag or supplier"),
    tags: Optional[List[str]] = Query(None, description="Lots carrying all of these tags"),
    in_stock: Optional[bool] = Query(None, description="true: quantity > 0; false: empty lots"),
    sort: SeedLotSort = "expiry",
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.list_seed_lots(
        actor, crop_master_id=crop_master_id, query=q, tags=tags, in_stock=in_stock, sort=sort
    )


@_both(
    router.post, "/seed-lots", response_model=SeedLotAddResult, status_code=status.HTTP_201_CREATED,
    summary="Add Seed Lot",
)
@inject
async def add_seed_lot(
    body: SeedLotCreate, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    return await inventory.add_seed_lot(actor, body)


@router.get("/seed-lots/match", response_model=Optional[SeedLotRead], summary="Find Lot Of Same Crop And Variety")
@inject
async def match_seed_lot(
    crop_master_id: UUID,
    variety_note: Optional[str] = None,
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.find_matching_lot(actor, crop_master_id, variety_note)


@router.get("/seed-lots/tags", response_model=List[SeedTagCount], summary="Seed Lot Tags In Use")
@inject
async def seed_tags(actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)):
    return await inventory.seed_tags(actor)


@router.post("/seed-lots/tags", response_model=List[SeedLotRead], summary="Tag Or Untag Seed Lots")
@inject
async def tag_seed_lots(
    body: SeedLotTagging, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    return await inventory.tag_seed_lots(actor, body)


@router.post("/seed-lots/merge", response_model=SeedLotRead, summary="Merge Seed Lots")
@inject
async def merge_seed_lots(
    body: SeedLotMerge, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    return await inventory.merge_seed_lots(actor, body)


@router.get("/seed-lots/{lot_id}", response_model=SeedLotRead, summary="Get Seed Lot")
@inject
async def get_seed_lot(
    lot_id: UUID, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    return await inventory.get_seed_lot(actor, lot_id)


@router.patch("/seed-lots/{lot_id}", response_model=SeedLotRead, summary="Update Seed Lot")
@inject
async def update_seed_lot(
    lot_id: UUID,
    body: SeedLotUpdate,
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.update_seed_lot(actor, lot_id, body)


@router.post("/seed-lots/{lot_id}/adjust", response_model=SeedLotAdjustResult, summary="Adjust Seed Stock")
@inject
async def adjust_seed_lot(
    lot_id: UUID,
    body: SeedLotAdjust,
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.adjust_seed_lot(actor, lot_id, body)


@router.post("/seed-lots/{lot_id}/consume", response_model=SeedLotAdjustResult, summary="Consume Seed Lot")
@inject
async def consume_seed_lot(
    lot_id: UUID,
    quantity: float = Body(..., embed=True, gt=0),
    unit: Optional[str] = Body(None, embed=True),
    actor: Actor = Depends(get_actor),
    inventory: InventoryService = Depends(INVENTORY),
):
    return await inventory.consume_seed_lot(actor, lot_id, quantity, unit)


@router.delete("/seed-lots/{lot_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Seed Lot")
@inject
async def delete_seed_lot(
    lot_id: UUID, actor: Actor = Depends(get_actor), inventory: InventoryService = Depends(INVENTORY)
):
    await inventory.delete_seed_lot(actor, lot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
