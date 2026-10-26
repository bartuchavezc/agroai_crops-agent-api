"""Red Km 0: the marketplace where the network's producers sell to nearby kitchens (restaurants, verdulerías,
hotels). Its tables live in their own Postgres schema, `market`, apart from the farm's.

Nothing sown is on sale by itself: a producer publishes a lot on purpose (a listing), and what buyers see is that
listing kept in step with the lot — a failed or harvested-out lot, or one inside a withholding period, stops
selling (see service.listing_state). Buyers have no account: an order carries their name and email, and a token
to follow it. Each order is split per producer (an order part), which the producer accepts, packs box by box and
leaves ready for the network's pickup route."""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

MARKET_SCHEMA = "market"

PLANS = ("free", "pro")
LISTING_STATUSES = ("published", "paused", "closed")  # the producer's intent; the lot can still stop it
CATEGORIES = ("hojas", "frutos", "aromaticas", "raices", "otros")
# nuevo → (accept) prep → (every box packed) listo → (picked up and handed over) entregado; or rechazado.
PART_STATUSES = ("nuevo", "prep", "listo", "entregado", "rechazado")
OPEN_PART_STATUSES = ("nuevo", "prep", "listo")
BUYER_KINDS = ("restaurante", "verduleria", "hotel", "comedor", "familia", "otro")


ORDER_CODES = Sequence("order_code_seq", schema=MARKET_SCHEMA, start=2001)


def _fk(table: str) -> str:
    return f"{MARKET_SCHEMA}.{table}.id"


class Producer(Base):
    """An account that sells in the network, from one of its fields (where the pickup happens)."""
    __tablename__ = "producers"
    __table_args__ = (
        CheckConstraint(f"plan IN {PLANS}", name="plan_valid"),
        {"schema": MARKET_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="RESTRICT"), nullable=False)
    display_name = Column(String(120), nullable=False)  # "Huerta Los Aromos"
    barrio = Column(String(120))
    plan = Column(String(10), nullable=False, default="free", server_default="free")
    # Set by the network after its audit: the agroecological seal buyers see.
    seal_until = Column(Date)
    active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Listing(Base):
    """A lot put on sale: price, how much a week and for how many weeks, and what's free this week."""
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint(f"status IN {LISTING_STATUSES}", name="status_valid"),
        CheckConstraint(f"category IN {CATEGORIES}", name="category_valid"),
        CheckConstraint("price_per_kg > 0", name="price_positive"),
        CheckConstraint("weekly_capacity_kg > 0", name="capacity_positive"),
        CheckConstraint("stock_kg >= 0", name="stock_not_negative"),
        Index("ix_listings_status", "status"),
        {"schema": MARKET_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    producer_id = Column(UUID(as_uuid=True), ForeignKey(_fk("producers"), ondelete="CASCADE"), nullable=False,
                         index=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(120), nullable=False)  # what the buyer reads: "Rúcula", "Tomate cherry"
    category = Column(String(20), nullable=False, default="otros")
    price_per_kg = Column(Float, nullable=False)
    weekly_capacity_kg = Column(Float, nullable=False)
    weeks = Column(Integer, nullable=False, default=1)
    stock_kg = Column(Float, nullable=False, default=0)  # free this week; orders take from it
    available_from = Column(Date)  # null: now. Later: a presale until then
    status = Column(String(10), nullable=False, default="published")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Order(Base):
    """What a buyer asked for, in one delivery and one invoice from the network. No account: the token (kept
    hashed) is how the buyer follows it."""
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint(f"buyer_kind IN {BUYER_KINDS}", name="buyer_kind_valid"),
        Index("ix_orders_buyer_email", "buyer_email"),
        {"schema": MARKET_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(Integer, ORDER_CODES, server_default=ORDER_CODES.next_value(), nullable=False, unique=True)  # #2041
    token_hash = Column(String(64), nullable=False)
    buyer_name = Column(String(160), nullable=False)
    buyer_email = Column(String(254), nullable=False)
    buyer_phone = Column(String(40))
    buyer_kind = Column(String(20), nullable=False, default="otro")
    delivery_address = Column(String(255), nullable=False)
    delivery_date = Column(Date, nullable=False)
    recurring = Column(Boolean, nullable=False, default=False)
    subtotal = Column(Float, nullable=False)
    logistics_fee = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class OrderPart(Base):
    """The share of an order one producer prepares. Fee and net are fixed when the order is placed, at the plan
    the producer had then."""
    __tablename__ = "order_parts"
    __table_args__ = (
        CheckConstraint(f"status IN {PART_STATUSES}", name="status_valid"),
        Index("ix_order_parts_account_status", "account_id", "status"),
        {"schema": MARKET_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey(_fk("orders"), ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    producer_id = Column(UUID(as_uuid=True), ForeignKey(_fk("producers"), ondelete="CASCADE"), nullable=False)
    status = Column(String(12), nullable=False, default="nuevo")
    pickup_date = Column(Date, nullable=False)
    gross = Column(Float, nullable=False)
    fee_rate = Column(Float, nullable=False)
    fee = Column(Float, nullable=False)
    net = Column(Float, nullable=False)
    packed = Column(JSONB, nullable=False, default=list, server_default="[]")  # box codes already packed
    reject_reason = Column(Text)
    accepted_at = Column(DateTime(timezone=True))
    ready_at = Column(DateTime(timezone=True))
    delivered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("kg > 0", name="kg_positive"),
        {"schema": MARKET_SCHEMA},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_id = Column(UUID(as_uuid=True), ForeignKey(_fk("order_parts"), ondelete="CASCADE"), nullable=False,
                     index=True)
    listing_id = Column(UUID(as_uuid=True), ForeignKey(_fk("listings"), ondelete="SET NULL"))
    title = Column(String(120), nullable=False)
    kg = Column(Float, nullable=False)
    price_per_kg = Column(Float, nullable=False)
    # Whether it took stock (a presale reserves against the weekly capacity instead): what a rejection gives back.
    from_stock = Column(Boolean, nullable=False, default=True)


class PickupRoute(Base):
    """A day's milk run: the driver goes by the producers in order, then to the hub where boxes are sorted."""
    __tablename__ = "pickup_routes"
    __table_args__ = ({"schema": MARKET_SCHEMA},)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_date = Column(Date, nullable=False, index=True)
    name = Column(String(80), nullable=False)  # "Ruta norte"
    driver_name = Column(String(120), nullable=False)
    hub_name = Column(String(120))
    hub_eta = Column(Time)
    deliveries_from = Column(Time)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class PickupStop(Base):
    __tablename__ = "pickup_stops"
    __table_args__ = ({"schema": MARKET_SCHEMA},)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    route_id = Column(UUID(as_uuid=True), ForeignKey(_fk("pickup_routes"), ondelete="CASCADE"), nullable=False,
                      index=True)
    producer_id = Column(UUID(as_uuid=True), ForeignKey(_fk("producers"), ondelete="CASCADE"), nullable=False,
                         index=True)
    position = Column(Integer, nullable=False)
    eta = Column(Time, nullable=False)
    picked_up_at = Column(DateTime(timezone=True))
