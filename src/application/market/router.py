"""Red Km 0 HTTP API.

- `/market/public/*`: no account. The catalog near a point, placing an order (name + email) and following it with
  the code and the token it returned.
- `/market/*`: the producer's side (bearer token): their profile and plan, the lots they publish, the orders they
  prepare and their panel.
- `/market/admin/*`: the network's operators (PLATFORM_ADMIN_EMAILS): pickup routes, delivery and the seal."""
from datetime import date
from typing import List, Literal, Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Query, Response, status

from src.auth.api.dependencies import get_actor, require_platform_admin
from src.auth.domain.schemas import UserRead
from src.shared.domain.actor import Actor

from .schemas import (
    BuyerOrderRead,
    Catalog,
    Dashboard,
    ListingCreate,
    ListingRead,
    ListingUpdate,
    LotCandidate,
    OrderCreate,
    OrderPlaced,
    PackedUpdate,
    PlanChange,
    ProducerOrderRead,
    ProducerRead,
    ProducerUpsert,
    RejectBody,
    RouteCreate,
    RouteRead,
    SealUpdate,
)
from .service import MarketService

router = APIRouter(prefix="/market", tags=["Market"])
MARKET = Provide["application.market_service"]


# ---------- public ----------

@router.get("/public/catalog", response_model=Catalog, summary="What the network's producers sell near a point")
@inject
async def catalog(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    radius_km: Optional[float] = Query(None, gt=0, le=200, description="Only producers this close (needs lat/lng)"),
    market: MarketService = Depends(MARKET),
):
    """Farms are shown at an approximate point (snapped to ~500 m), never their exact location."""
    return await market.catalog(lat, lng, radius_km)


@router.post("/public/orders", response_model=OrderPlaced, status_code=status.HTTP_201_CREATED,
             summary="Place an order without an account")
@inject
async def place_order(body: OrderCreate, market: MarketService = Depends(MARKET)):
    """Takes what's free this week (or reserves a presale against the weekly capacity), splits the order per
    producer and notifies each one. The `token` is returned only here: with the `code` it opens the order."""
    return await market.place_order(body)


@router.get("/public/orders/{code}", response_model=BuyerOrderRead, summary="Follow an order")
@inject
async def buyer_order(code: int, token: str = Query(..., min_length=10), market: MarketService = Depends(MARKET)):
    return await market.buyer_order(code, token)


# ---------- producer ----------

@router.get("/me", response_model=Optional[ProducerRead], summary="This account's producer profile (null: not yet)")
@inject
async def get_me(actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.get_producer(actor)


@router.put("/me", response_model=ProducerRead, summary="Sell in the network from a field (owner/tecnico)")
@inject
async def put_me(body: ProducerUpsert, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.upsert_producer(actor, body)


@router.put("/me/plan", response_model=ProducerRead, summary="Free (20%) or Pro (8% + subscription), owner only")
@inject
async def put_plan(body: PlanChange, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    """Applies to orders placed from now on; those already placed keep their fee."""
    return await market.set_plan(actor, body.plan)


@router.get("/dashboard", response_model=Dashboard, summary="The producer's panel")
@inject
async def dashboard(actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.dashboard(actor)


@router.get("/lots", response_model=List[LotCandidate], summary="The account's lots, and whether each can be published")
@inject
async def lot_candidates(actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.lot_candidates(actor)


@router.get("/listings", response_model=List[ListingRead], summary="What this account publishes")
@inject
async def list_listings(
    include_closed: bool = False, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)
):
    """Each with `on_sale` and, when off sale, `hidden_reason`: the lot (failed, harvested, deleted) decides too."""
    return await market.list_listings(actor, include_closed)


@router.post("/listings", response_model=ListingRead, status_code=status.HTTP_201_CREATED,
             summary="Publish a lot (owner/tecnico)")
@inject
async def create_listing(body: ListingCreate, actor: Actor = Depends(get_actor),
                         market: MarketService = Depends(MARKET)):
    """Only a lot in the ground (seedbed to harvesting). Title, price and date start from the lot."""
    return await market.create_listing(actor, body)


@router.put("/listings/{listing_id}", response_model=ListingRead, summary="Update a listing")
@inject
async def update_listing(listing_id: UUID, body: ListingUpdate, actor: Actor = Depends(get_actor),
                         market: MarketService = Depends(MARKET)):
    """Any member updates `stock_kg`; the rest (price, pause...) is owner/tecnico."""
    return await market.update_listing(actor, listing_id, body)


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Stop selling a lot")
@inject
async def close_listing(listing_id: UUID, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    await market.close_listing(actor, listing_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/orders", response_model=List[ProducerOrderRead], summary="Orders to prepare, or past ones")
@inject
async def list_orders(scope: Literal["active", "done"] = "active", actor: Actor = Depends(get_actor),
                      market: MarketService = Depends(MARKET)):
    return await market.list_orders(actor, scope)


@router.get("/orders/{part_id}", response_model=ProducerOrderRead, summary="One order")
@inject
async def get_order(part_id: UUID, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.get_order(actor, part_id)


@router.post("/orders/{part_id}/accept", response_model=ProducerOrderRead, summary="Accept (owner/tecnico)")
@inject
async def accept_order(part_id: UUID, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.accept(actor, part_id)


@router.post("/orders/{part_id}/reject", response_model=ProducerOrderRead, summary="Can't make it (owner/tecnico)")
@inject
async def reject_order(part_id: UUID, body: RejectBody, actor: Actor = Depends(get_actor),
                       market: MarketService = Depends(MARKET)):
    return await market.reject(actor, part_id, body.reason)


@router.put("/orders/{part_id}/packed", response_model=ProducerOrderRead, summary="The boxes packed so far")
@inject
async def set_packed(part_id: UUID, body: PackedUpdate, actor: Actor = Depends(get_actor),
                     market: MarketService = Depends(MARKET)):
    return await market.set_packed(actor, part_id, body.packed)


@router.post("/orders/{part_id}/ready", response_model=ProducerOrderRead, summary="Ready for pickup")
@inject
async def mark_ready(part_id: UUID, actor: Actor = Depends(get_actor), market: MarketService = Depends(MARKET)):
    return await market.mark_ready(actor, part_id)


# ---------- the network's operators ----------

@router.get("/admin/producers", response_model=List[ProducerRead], summary="Every producer in the network")
@inject
async def admin_producers(_: UserRead = Depends(require_platform_admin), market: MarketService = Depends(MARKET)):
    return await market.list_producers()


@router.put("/admin/producers/{producer_id}/seal", response_model=ProducerRead, summary="Grant or revoke the seal")
@inject
async def admin_seal(producer_id: UUID, body: SealUpdate, _: UserRead = Depends(require_platform_admin),
                     market: MarketService = Depends(MARKET)):
    return await market.set_seal(producer_id, body.seal_until)


@router.get("/admin/routes", response_model=List[RouteRead], summary="Pickup routes from a day on")
@inject
async def admin_routes(since: date, _: UserRead = Depends(require_platform_admin),
                       market: MarketService = Depends(MARKET)):
    return await market.list_routes(since)


@router.post("/admin/routes", response_model=RouteRead, status_code=status.HTTP_201_CREATED,
             summary="Plan a day's pickup route")
@inject
async def admin_create_route(body: RouteCreate, _: UserRead = Depends(require_platform_admin),
                             market: MarketService = Depends(MARKET)):
    return await market.create_route(body)


@router.post("/admin/order-parts/{part_id}/deliver", status_code=status.HTTP_204_NO_CONTENT,
             summary="Picked up and handed to the buyer")
@inject
async def admin_deliver(part_id: UUID, _: UserRead = Depends(require_platform_admin),
                        market: MarketService = Depends(MARKET)):
    await market.deliver(part_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
