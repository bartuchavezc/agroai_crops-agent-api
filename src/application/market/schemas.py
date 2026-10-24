from datetime import date, datetime, time
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field as PField

Plan = Literal["free", "pro"]
Category = Literal["hojas", "frutos", "aromaticas", "raices", "otros"]
ListingStatus = Literal["published", "paused", "closed"]
PartStatus = Literal["nuevo", "prep", "listo", "entregado", "rechazado"]
BuyerKind = Literal["restaurante", "verduleria", "hotel", "comedor", "familia", "otro"]
AvailabilityKind = Literal["now", "from", "presale"]
# Why a published listing is not on sale right now (the lot decides): it was never sown, it failed, it is all
# harvested, or it was deleted. A withholding period (carencia) does not hide it: it pushes its date.
HiddenReason = Literal["paused", "closed", "lot_not_sown", "lot_failed", "lot_harvested", "lot_deleted",
                       "producer_inactive"]


# ---------- producer profile ----------

class ProducerUpsert(BaseModel):
    field_id: UUID = PField(description="The field the pickup happens at; it needs coordinates")
    display_name: str = PField(min_length=2, max_length=120)
    barrio: Optional[str] = PField(default=None, max_length=120)


class ProducerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    field_id: UUID
    display_name: str
    barrio: Optional[str] = None
    plan: Plan
    seal_until: Optional[date] = None
    active: bool
    created_at: datetime


class PlanChange(BaseModel):
    plan: Plan


# ---------- listings ----------

class Availability(BaseModel):
    kind: AvailabilityKind
    from_date: Optional[date] = PField(default=None, alias="from")

    model_config = ConfigDict(populate_by_name=True)


class ListingCreate(BaseModel):
    lot_id: UUID
    title: Optional[str] = PField(default=None, max_length=120, description="By default, the crop's name")
    category: Category = "otros"
    price_per_kg: Optional[float] = PField(default=None, gt=0, description="By default, the lot's expected_price")
    weekly_capacity_kg: float = PField(gt=0, le=10_000)
    weeks: int = PField(default=1, ge=1, le=52)
    stock_kg: float = PField(default=0, ge=0, le=10_000)
    available_from: Optional[date] = PField(default=None, description="Null: now. By default the lot's expected "
                                                                      "harvest date if it is ahead")
    notes: Optional[str] = PField(default=None, max_length=1000)


class ListingUpdate(BaseModel):
    title: Optional[str] = PField(default=None, min_length=1, max_length=120)
    category: Optional[Category] = None
    price_per_kg: Optional[float] = PField(default=None, gt=0)
    weekly_capacity_kg: Optional[float] = PField(default=None, gt=0, le=10_000)
    weeks: Optional[int] = PField(default=None, ge=1, le=52)
    stock_kg: Optional[float] = PField(default=None, ge=0, le=10_000)
    available_from: Optional[date] = None
    status: Optional[ListingStatus] = None
    notes: Optional[str] = PField(default=None, max_length=1000)


class ListingRead(BaseModel):
    """A listing as its producer sees it: with whether it is on sale and, if not, why."""
    id: UUID
    lot_id: UUID
    lot_label: Optional[str] = None
    lot_status: Optional[str] = None
    title: str
    category: Category
    price_per_kg: float
    weekly_capacity_kg: float
    weeks: int
    stock_kg: float
    available_from: Optional[date] = None
    status: ListingStatus
    notes: Optional[str] = None
    on_sale: bool
    hidden_reason: Optional[HiddenReason] = None
    availability: Availability
    harvest_blocked_until: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class LotCandidate(BaseModel):
    """A lot of the account that could be published, with what the listing would start from."""
    lot_id: UUID
    label: str
    crop_name: str
    status: str
    field_id: UUID
    expected_harvest_date: Optional[date] = None
    expected_yield_kg: Optional[float] = None
    expected_price: Optional[float] = None
    harvest_blocked_until: Optional[date] = None
    listed: bool
    publishable: bool  # in the ground: a planned (unsown) lot can't be sold yet


# ---------- public catalog ----------

class PublicProducer(BaseModel):
    id: UUID
    name: str
    barrio: Optional[str] = None
    lat: float
    lng: float
    distance_km: Optional[float] = None
    sealed: bool
    traceability_pct: Optional[int] = PField(
        default=None, description="Share of its listed lots with a bitácora entry in the last 14 days"
    )
    listing_count: int


class PublicListing(BaseModel):
    id: UUID
    producer_id: UUID
    title: str
    category: Category
    price_per_kg: float
    weekly_capacity_kg: float
    weeks: int
    stock_kg: float
    availability: Availability
    order_step_kg: float


class Delivery(BaseModel):
    date: date
    window: str


class Catalog(BaseModel):
    producers: list[PublicProducer]
    listings: list[PublicListing]
    delivery: Delivery
    currency: str
    logistics_fee: float
    free_logistics_from: float


# ---------- orders ----------

class BuyerIn(BaseModel):
    name: str = PField(min_length=2, max_length=160)
    email: EmailStr
    phone: Optional[str] = PField(default=None, max_length=40)
    kind: BuyerKind = "otro"
    address: str = PField(min_length=4, max_length=255)


class OrderItemIn(BaseModel):
    listing_id: UUID
    kg: float = PField(gt=0, le=500)


class OrderCreate(BaseModel):
    buyer: BuyerIn
    items: list[OrderItemIn] = PField(min_length=1, max_length=40)
    recurring: bool = False


class OrderItemRead(BaseModel):
    title: str
    kg: float
    price_per_kg: float
    total: float
    from_stock: bool


class BuyerPartRead(BaseModel):
    producer_name: str
    status: PartStatus
    items: list[OrderItemRead]
    subtotal: float


class BuyerOrderRead(BaseModel):
    code: int
    buyer_name: str
    buyer_email: str
    delivery_address: str
    delivery_date: date
    delivery_window: str
    recurring: bool
    status: Literal["recibido", "en_preparacion", "en_camino", "entregado", "cancelado"]
    parts: list[BuyerPartRead]
    subtotal: float
    logistics_fee: float
    total: float
    created_at: datetime


class OrderPlaced(BuyerOrderRead):
    token: str = PField(description="Shown once: with the code, the only way to follow the order")


class Box(BaseModel):
    code: str
    title: str
    index: int
    count: int
    kg: float
    packed: bool


class ProducerOrderRead(BaseModel):
    """An order part, as the producer prepares it."""
    id: UUID
    code: int
    buyer_name: str
    buyer_kind: BuyerKind
    status: PartStatus
    pickup_date: date
    delivery_date: date
    items: list[OrderItemRead]
    boxes: list[Box]
    gross: float
    fee_rate: float
    fee: float
    net: float
    reject_reason: Optional[str] = None
    accepted_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    created_at: datetime


class PackedUpdate(BaseModel):
    packed: list[str] = PField(max_length=400, description="The box codes packed so far")


class RejectBody(BaseModel):
    reason: str = PField(min_length=2, max_length=500)


# ---------- dashboard ----------

class RouteStopRead(BaseModel):
    producer_name: str
    eta: time
    is_me: bool
    picked_up: bool


class TodayRoute(BaseModel):
    id: UUID
    route_date: date
    name: str
    driver_name: str
    my_eta: Optional[time] = None
    stops: list[RouteStopRead]
    hub_name: Optional[str] = None
    hub_eta: Optional[time] = None
    deliveries_from: Optional[time] = None


class SaleRow(BaseModel):
    code: int
    delivered_on: date
    buyer_name: str
    kg: float
    gross: float
    fee: float
    net: float


class PlanMonth(BaseModel):
    plan: Plan
    gross: float
    fee_rate: float
    fee: float
    subscription: float
    net: float
    other_plan_cost: float
    saving_vs_other: float
    next_month_discount: float


class Dashboard(BaseModel):
    producer: ProducerRead
    month_label: str
    month_sales: float
    month_orders: int
    settlement_date: date
    to_collect: float
    active_orders: int
    active_kg: float
    boxes_total: int
    boxes_ready: int
    route: Optional[TodayRoute] = None
    sales: list[SaleRow]
    plan_month: PlanMonth
    currency: str


# ---------- platform admin: routes and delivery ----------

class RouteStopIn(BaseModel):
    producer_id: UUID
    eta: time


class RouteCreate(BaseModel):
    route_date: date
    name: str = PField(min_length=1, max_length=80)
    driver_name: str = PField(min_length=1, max_length=120)
    hub_name: Optional[str] = PField(default=None, max_length=120)
    hub_eta: Optional[time] = None
    deliveries_from: Optional[time] = None
    stops: list[RouteStopIn] = PField(min_length=1, max_length=40)


class RouteRead(BaseModel):
    id: UUID
    route_date: date
    name: str
    driver_name: str
    hub_name: Optional[str] = None
    stops: list[RouteStopIn]


class SealUpdate(BaseModel):
    seal_until: Optional[date] = None
