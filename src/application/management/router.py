from typing import List, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Response, status

from src.auth.api.dependencies import get_actor
from src.shared.domain.actor import Actor
from src.shared.utils.routing import route_with_and_without_slash as _both

from .schemas import (
    BudgetEntryCreate,
    BudgetEntryRead,
    BudgetSummary,
    RoadmapItemCreate,
    RoadmapItemRead,
    RoadmapItemUpdate,
    ShoppingItemCreate,
    ShoppingItemRead,
    ShoppingItemUpdate,
)
from .service import ManagementService

router = APIRouter(prefix="/management", tags=["Management"])

MANAGEMENT = Provide["application.management_service"]


# ---------- shopping list ----------

@_both(router.get, "/shopping-list", response_model=List[ShoppingItemRead], summary="List Shopping List")
@inject
async def list_shopping_list(
    field_id: Optional[UUID] = None, status_filter: Optional[str] = None,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.list_shopping_list(actor, field_id=field_id, status=status_filter)


@_both(
    router.post, "/shopping-list", response_model=ShoppingItemRead, status_code=status.HTTP_201_CREATED,
    summary="Add Shopping Item",
)
@inject
async def add_shopping_item(
    body: ShoppingItemCreate, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    return await management.add_shopping_item(actor, body)


@router.put("/shopping-list/{item_id}", response_model=ShoppingItemRead, summary="Update Shopping Item")
@inject
async def update_shopping_item(
    item_id: UUID, body: ShoppingItemUpdate,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.update_shopping_item(actor, item_id, body)


@router.delete("/shopping-list/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Shopping Item")
@inject
async def delete_shopping_item(
    item_id: UUID, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    await management.delete_shopping_item(actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- budget ----------

@_both(router.get, "/budget", response_model=List[BudgetEntryRead], summary="List Budget Entries")
@inject
async def list_budget(
    field_id: Optional[UUID] = None, since: Optional[str] = None, until: Optional[str] = None,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.list_budget(actor, field_id=field_id, since=since, until=until)


@_both(
    router.post, "/budget", response_model=BudgetEntryRead, status_code=status.HTTP_201_CREATED,
    summary="Add Budget Entry",
)
@inject
async def add_budget_entry(
    body: BudgetEntryCreate, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    return await management.add_budget_entry(actor, body)


@router.get("/budget/summary", response_model=BudgetSummary, summary="Budget Summary")
@inject
async def get_budget_summary(
    field_id: Optional[UUID] = None, since: Optional[str] = None, until: Optional[str] = None,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.get_budget_summary(actor, field_id=field_id, since=since, until=until)


@router.delete("/budget/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Budget Entry")
@inject
async def delete_budget_entry(
    entry_id: UUID, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    await management.delete_budget_entry(actor, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- roadmap ----------

@_both(router.get, "/roadmap", response_model=List[RoadmapItemRead], summary="List Roadmap")
@inject
async def list_roadmap(
    field_id: Optional[UUID] = None, status_filter: Optional[str] = None,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.list_roadmap(actor, field_id=field_id, status=status_filter)


@_both(
    router.post, "/roadmap", response_model=RoadmapItemRead, status_code=status.HTTP_201_CREATED,
    summary="Add Roadmap Item",
)
@inject
async def add_roadmap_item(
    body: RoadmapItemCreate, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    return await management.add_roadmap_item(actor, body)


@router.put("/roadmap/{item_id}", response_model=RoadmapItemRead, summary="Update Roadmap Item")
@inject
async def update_roadmap_item(
    item_id: UUID, body: RoadmapItemUpdate,
    actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT),
):
    return await management.update_roadmap_item(actor, item_id, body)


@router.delete("/roadmap/{item_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete Roadmap Item")
@inject
async def delete_roadmap_item(
    item_id: UUID, actor: Actor = Depends(get_actor), management: ManagementService = Depends(MANAGEMENT)
):
    await management.delete_roadmap_item(actor, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
