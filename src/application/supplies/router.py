from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.application.products.service import ProductRegistryService, RegisteredProduct, RegistryKind
from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import (
    SupplyItemCreate,
    SupplyItemRead,
    SupplyItemUpdate,
    SupplyMovementCreate,
    SupplyMovementRead,
    SupplyKind,
)
from .service import SupplyService

router = APIRouter(prefix="/supplies", tags=["Supplies"])

SUPPLIES = Provide["application.supply_service"]
REGISTRY = Provide["application.product_registry_service"]


@router.get("/registry", response_model=List[RegisteredProduct], summary="Search the products registry")
@inject
async def search_registry(
    q: str = Query(..., min_length=2, description="Brand (partial) or registry number"),
    kind: Optional[RegistryKind] = None,
    limit: int = Query(10, ge=1, le=30),
    actor: Actor = Depends(get_actor),
    registry: ProductRegistryService = Depends(REGISTRY),
):
    """Products REGISTERED in the user's country (SENASA in Argentina): their formal text, to copy into a stock item
    or an application. Being registered is not being authorised for a given crop."""
    return await registry.search(q, country=actor.country, kind=kind, limit=limit)


@_both(router.get, "/items", response_model=List[SupplyItemRead], summary="List inputs in stock")
@inject
async def list_items(
    q: Optional[str] = None,
    kind: Optional[SupplyKind] = None,
    in_stock: Optional[bool] = None,
    expiring_within_days: Optional[int] = Query(None, ge=0, le=3650),
    actor: Actor = Depends(get_actor),
    supplies: SupplyService = Depends(SUPPLIES),
):
    return await supplies.list_items(
        actor, query=q, kind=kind, in_stock=in_stock, expiring_within_days=expiring_within_days
    )


@_both(router.post, "/items", response_model=SupplyItemRead, status_code=status.HTTP_201_CREATED,
       summary="Take an input into stock")
@inject
async def create_item(
    body: SupplyItemCreate, actor: Actor = Depends(get_actor), supplies: SupplyService = Depends(SUPPLIES)
):
    return await supplies.create_item(actor, body)


@router.get("/items/{item_id}", response_model=SupplyItemRead, summary="Get an input")
@inject
async def get_item(item_id: UUID, actor: Actor = Depends(get_actor), supplies: SupplyService = Depends(SUPPLIES)):
    return await supplies.get_item(actor, item_id)


@router.put("/items/{item_id}", response_model=SupplyItemRead, summary="Fix an input's data (owner/tecnico)")
@inject
async def update_item(
    item_id: UUID, body: SupplyItemUpdate, actor: Actor = Depends(get_actor),
    supplies: SupplyService = Depends(SUPPLIES),
):
    return await supplies.update_item(actor, item_id, body)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an input from stock")
@inject
async def delete_item(item_id: UUID, actor: Actor = Depends(get_actor), supplies: SupplyService = Depends(SUPPLIES)):
    await supplies.delete_item(actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/items/{item_id}/movements", response_model=List[SupplyMovementRead], summary="An input's ledger")
@inject
async def movements(
    item_id: UUID, limit: int = Query(100, ge=1, le=500), actor: Actor = Depends(get_actor),
    supplies: SupplyService = Depends(SUPPLIES),
):
    return await supplies.movements(actor, item_id, limit)


@router.post("/items/{item_id}/movements", response_model=SupplyItemRead, status_code=status.HTTP_201_CREATED,
             summary="A receipt, or an adjustment with its reason")
@inject
async def add_movement(
    item_id: UUID, body: SupplyMovementCreate, actor: Actor = Depends(get_actor),
    supplies: SupplyService = Depends(SUPPLIES),
):
    """Consumptions are written by confirmed applications, never by hand."""
    return await supplies.add_movement(actor, item_id, body)
