"""Red Km 0: producers publish lots, buyers order without an account, producers prepare their share and the
network picks it up. See models.py for the shape of it.

The catalog is public, so it reads across accounts; everything a producer does goes through their Actor and is
scoped by account, and lots are reached through the farm service (its own permission checks)."""
import hashlib
import hmac
import logging
import secrets
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import GROWING_LOT_STATUSES, CropMaster, EventLot, Field, FieldEvent, Lot
from src.auth.domain.models import Account
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.domain.locale import today_in
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from . import rules
from .models import OPEN_PART_STATUSES, Listing, Order, OrderItem, OrderPart, PickupRoute, PickupStop, Producer
from .schemas import (
    Availability,
    BuyerOrderRead,
    BuyerPartRead,
    Catalog,
    Dashboard,
    Delivery,
    ListingCreate,
    ListingRead,
    ListingUpdate,
    LotCandidate,
    OrderCreate,
    OrderItemRead,
    OrderPlaced,
    PlanMonth,
    ProducerOrderRead,
    ProducerRead,
    ProducerUpsert,
    PublicListing,
    PublicProducer,
    RouteCreate,
    RouteRead,
    RouteStopIn,
    RouteStopRead,
    SaleRow,
    TodayRoute,
)

logger = logging.getLogger(__name__)

MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
TRACE_DAYS = 14


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only the owner or a tecnico can do this.")


def listing_state(listing: Listing, lot: Optional[Lot], producer_active: bool, today: date) -> dict:
    """Whether a listing is on sale now, kept in step with its lot. A withholding period (carencia) doesn't hide
    it: nothing can be harvested before the day after it ends, so that becomes its date."""
    reason = None
    if listing.status != "published":
        reason = listing.status
    elif not producer_active:
        reason = "producer_inactive"
    elif lot is None or lot.deleted_at is not None:
        reason = "lot_deleted"
    elif lot.status == "failed":
        reason = "lot_failed"
    elif lot.status == "harvested":
        reason = "lot_harvested"
    elif lot.status not in GROWING_LOT_STATUSES:
        reason = "lot_not_sown"
    available_from = listing.available_from
    blocked = lot.harvest_blocked_until if lot is not None else None
    if blocked is not None and blocked >= today:
        available_from = max(available_from or today, blocked + timedelta(days=1))
    avail = rules.availability(available_from, today, lot.status if lot is not None else "")
    return {"on_sale": reason is None, "reason": reason, "availability": avail, "available_from": available_from}


class MarketService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        farm_service,
        notification_service,
        config: dict,
        timezone_name: str,
    ):
        self.session_factory = session_factory
        self.farm = farm_service
        self.notifications = notification_service
        self.config = config
        self.tz = timezone_name

    # ---------- calendar ----------

    def today(self) -> date:
        return today_in(self.tz)

    def delivery_window(self) -> str:
        return self.config["delivery_window"]

    def next_delivery(self, earliest: Optional[date] = None) -> date:
        today = self.today()
        start = today if earliest is None else max(today, earliest - timedelta(days=self.config["cutoff_days"]))
        return rules.next_delivery(start, self.config["delivery_weekday"], self.config["cutoff_days"])

    # ---------- producer profile ----------

    async def _producer(self, session: AsyncSession, account_id: UUID) -> Optional[Producer]:
        return (await session.execute(select(Producer).where(Producer.account_id == account_id))).scalar_one_or_none()

    async def _my_producer(self, session: AsyncSession, actor: Actor) -> Producer:
        producer = await self._producer(session, actor.account_id)
        if producer is None:
            raise NotFoundError("This account doesn't sell in the network yet.")
        return producer

    async def get_producer(self, actor: Actor) -> Optional[ProducerRead]:
        async with self.session_factory() as session:
            producer = await self._producer(session, actor.account_id)
        return ProducerRead.model_validate(producer) if producer else None

    async def upsert_producer(self, actor: Actor, data: ProducerUpsert) -> ProducerRead:
        _require_manager(actor)
        field = await self.farm.get_field(actor, data.field_id)
        if field.latitude is None or field.longitude is None:
            raise InvalidInputError("The field needs its location before selling: buyers see the distance to it.")
        async with self.session_factory() as session:
            producer = await self._producer(session, actor.account_id)
            if producer is None:
                producer = Producer(account_id=actor.account_id)
                session.add(producer)
            producer.field_id = data.field_id
            producer.display_name = data.display_name.strip()
            producer.barrio = (data.barrio or "").strip() or field.city
            await session.commit()
            await session.refresh(producer)
        return ProducerRead.model_validate(producer)

    async def set_plan(self, actor: Actor, plan: str) -> ProducerRead:
        if not actor.is_owner:
            raise PermissionDeniedError("Only the owner changes the plan.")
        async with self.session_factory() as session:
            producer = await self._my_producer(session, actor)
            producer.plan = plan
            await session.commit()
            await session.refresh(producer)
        return ProducerRead.model_validate(producer)

    # ---------- listings ----------

    async def _crop_names(self, session: AsyncSession, crop_ids: Iterable[UUID], locale: str) -> dict[UUID, str]:
        ids = list(set(crop_ids))
        if not ids:
            return {}
        rows = (await session.execute(select(CropMaster).where(CropMaster.id.in_(ids)))).scalars().all()
        return {c.id: (c.i18n or {}).get(locale) or c.name for c in rows}

    async def lot_candidates(self, actor: Actor) -> list[LotCandidate]:
        lots = [lot for lot in await self.farm.list_lots(actor) if lot.status not in ("harvested", "failed")]
        async with self.session_factory() as session:
            names = await self._crop_names(session, (lot.crop_master_id for lot in lots), actor.locale)
            listed = set((await session.execute(
                select(Listing.lot_id).where(Listing.account_id == actor.account_id, Listing.status != "closed")
            )).scalars().all())
        return [
            LotCandidate(
                lot_id=lot.id, label=lot.label or names.get(lot.crop_master_id, ""),
                crop_name=names.get(lot.crop_master_id, ""), status=lot.status, field_id=lot.field_id,
                expected_harvest_date=lot.expected_harvest_date, expected_yield_kg=lot.expected_yield_kg,
                expected_price=lot.expected_price, harvest_blocked_until=lot.harvest_blocked_until,
                listed=lot.id in listed, publishable=lot.status in GROWING_LOT_STATUSES,
            )
            for lot in lots
        ]

    def _listing_read(self, listing: Listing, lot: Optional[Lot], label: Optional[str], producer_active: bool,
                      today: date) -> ListingRead:
        state = listing_state(listing, lot, producer_active, today)
        return ListingRead(
            id=listing.id, lot_id=listing.lot_id, lot_label=label, lot_status=lot.status if lot else None,
            title=listing.title, category=listing.category, price_per_kg=listing.price_per_kg,
            weekly_capacity_kg=listing.weekly_capacity_kg, weeks=listing.weeks, stock_kg=listing.stock_kg,
            available_from=listing.available_from, status=listing.status, notes=listing.notes,
            on_sale=state["on_sale"], hidden_reason=state["reason"], availability=Availability(**state["availability"]),
            harvest_blocked_until=lot.harvest_blocked_until if lot else None,
            created_at=listing.created_at, updated_at=listing.updated_at,
        )

    async def _reads(self, actor: Actor, session: AsyncSession, listings: list[Listing],
                     producer: Producer) -> list[ListingRead]:
        lot_ids = [listing.lot_id for listing in listings]
        lots = {}
        if lot_ids:
            lots = {lot.id: lot for lot in (await session.execute(select(Lot).where(Lot.id.in_(lot_ids)))).scalars()}
        labels = {}
        live = [lot for lot in lots.values() if lot.deleted_at is None]
        if live:
            labels = {read.id: read.label for read in await self.farm.lot_reads(actor, live)}
        today = self.today()
        return [
            self._listing_read(listing, lots.get(listing.lot_id), labels.get(listing.lot_id), producer.active, today)
            for listing in listings
        ]

    async def list_listings(self, actor: Actor, include_closed: bool = False) -> list[ListingRead]:
        async with self.session_factory() as session:
            producer = await self._producer(session, actor.account_id)
            if producer is None:
                return []
            stmt = select(Listing).where(Listing.account_id == actor.account_id)
            if not include_closed:
                stmt = stmt.where(Listing.status != "closed")
            listings = list((await session.execute(stmt.order_by(Listing.created_at.desc()))).scalars())
            return await self._reads(actor, session, listings, producer)

    async def _my_listing(self, session: AsyncSession, actor: Actor, listing_id: UUID) -> Listing:
        listing = (await session.execute(
            select(Listing).where(Listing.id == listing_id, Listing.account_id == actor.account_id)
        )).scalar_one_or_none()
        if listing is None:
            raise NotFoundError(f"Listing {listing_id} not found.")
        return listing

    async def create_listing(self, actor: Actor, data: ListingCreate) -> ListingRead:
        _require_manager(actor)
        lot = await self.farm.get_lot(actor, data.lot_id)
        if lot.status not in GROWING_LOT_STATUSES:
            raise InvalidInputError("Only a lot in the ground can be published: sow it first.")
        async with self.session_factory() as session:
            producer = await self._my_producer(session, actor)
            taken = (await session.execute(select(Listing.id).where(
                Listing.lot_id == lot.id, Listing.status != "closed"
            ))).first()
            if taken:
                raise InvalidInputError("That lot is already published.")
            price = data.price_per_kg or lot.expected_price
            if not price:
                raise InvalidInputError("Set a price per kg (the lot has no expected price).")
            title = data.title or (await self._crop_names(session, [lot.crop_master_id], actor.locale)).get(
                lot.crop_master_id, "Cosecha"
            )
            available_from = data.available_from
            if "available_from" not in data.model_fields_set and lot.expected_harvest_date \
                    and lot.expected_harvest_date > self.today():
                available_from = lot.expected_harvest_date
            listing = Listing(
                account_id=actor.account_id, producer_id=producer.id, lot_id=lot.id, title=title.strip(),
                category=data.category, price_per_kg=price, weekly_capacity_kg=data.weekly_capacity_kg,
                weeks=data.weeks, stock_kg=data.stock_kg, available_from=available_from, status="published",
                notes=data.notes,
            )
            session.add(listing)
            await session.commit()
            await session.refresh(listing)
            return (await self._reads(actor, session, [listing], producer))[0]

    async def update_listing(self, actor: Actor, listing_id: UUID, data: ListingUpdate) -> ListingRead:
        values = data.model_dump(exclude_unset=True)
        # Day to day, anyone in the account updates what's free this week; the rest is the manager's.
        if set(values) - {"stock_kg"}:
            _require_manager(actor)
        async with self.session_factory() as session:
            producer = await self._my_producer(session, actor)
            listing = await self._my_listing(session, actor, listing_id)
            if listing.status == "closed":
                raise InvalidInputError("The listing is closed: publish the lot again.")
            for key, value in values.items():
                if value is None and key not in ("available_from", "notes"):
                    continue
                setattr(listing, key, value)
            await session.commit()
            await session.refresh(listing)
            return (await self._reads(actor, session, [listing], producer))[0]

    async def close_listing(self, actor: Actor, listing_id: UUID) -> None:
        _require_manager(actor)
        async with self.session_factory() as session:
            listing = await self._my_listing(session, actor, listing_id)
            listing.status = "closed"
            await session.commit()

    # ---------- public catalog ----------

    async def _on_sale(self, session: AsyncSession, today: date, for_update: bool = False,
                       listing_ids: Optional[list[UUID]] = None):
        """(listing, lot, producer, field lat/lng, state) of everything published by an active producer."""
        stmt = (
            select(Listing, Lot, Producer, Field.latitude, Field.longitude)
            .join(Producer, Producer.id == Listing.producer_id)
            .join(Lot, Lot.id == Listing.lot_id)
            .join(Field, Field.id == Producer.field_id)
            .where(Listing.status == "published", Producer.active.is_(True), Field.deleted_at.is_(None))
        )
        if listing_ids is not None:
            stmt = stmt.where(Listing.id.in_(listing_ids))
        if for_update:
            stmt = stmt.with_for_update(of=Listing)
        out = []
        for listing, lot, producer, lat, lng in (await session.execute(stmt)).all():
            state = listing_state(listing, lot, producer.active, today)
            if state["on_sale"] and lat is not None and lng is not None:
                out.append((listing, lot, producer, lat, lng, state))
        return out

    async def _traceability(self, session: AsyncSession, lot_ids: list[UUID]) -> set[UUID]:
        """The lots with something in the bitácora lately: what backs the network's word to the buyer."""
        if not lot_ids:
            return set()
        since = utcnow() - timedelta(days=TRACE_DAYS)
        rows = await session.execute(
            select(EventLot.lot_id).join(FieldEvent, FieldEvent.id == EventLot.event_id)
            .where(EventLot.lot_id.in_(lot_ids), FieldEvent.occurred_at >= since).distinct()
        )
        return set(rows.scalars().all())

    async def catalog(self, lat: Optional[float], lng: Optional[float], radius_km: Optional[float]) -> Catalog:
        today = self.today()
        async with self.session_factory() as session:
            rows = await self._on_sale(session, today)
            traced = await self._traceability(session, [lot.id for _, lot, *_ in rows])
        by_producer: dict[UUID, dict] = {}
        listings = []
        for listing, lot, producer, f_lat, f_lng, state in rows:
            p_lat, p_lng = rules.public_point(f_lat, f_lng, self.config["public_point_grid"])
            dist = round(rules.distance_km(lat, lng, p_lat, p_lng), 1) if lat is not None and lng is not None \
                else None
            if radius_km is not None and dist is not None and dist > radius_km:
                continue
            entry = by_producer.setdefault(producer.id, {
                "producer": producer, "lat": p_lat, "lng": p_lng, "dist": dist, "lots": [],
            })
            entry["lots"].append(lot.id)
            listings.append((dist, PublicListing(
                id=listing.id, producer_id=producer.id, title=listing.title, category=listing.category,
                price_per_kg=listing.price_per_kg, weekly_capacity_kg=listing.weekly_capacity_kg,
                weeks=listing.weeks,
                stock_kg=listing.stock_kg if state["availability"]["kind"] == "now" else 0.0,
                availability=Availability(**state["availability"]), order_step_kg=rules.ORDER_STEP_KG,
            )))
        producers = [
            PublicProducer(
                id=pid, name=e["producer"].display_name, barrio=e["producer"].barrio, lat=e["lat"], lng=e["lng"],
                distance_km=e["dist"], sealed=bool(e["producer"].seal_until and e["producer"].seal_until >= today),
                traceability_pct=round(100 * len(traced.intersection(e["lots"])) / len(e["lots"])),
                listing_count=len(e["lots"]),
            )
            for pid, e in by_producer.items()
        ]
        far = float("inf")
        producers.sort(key=lambda p: (p.distance_km if p.distance_km is not None else far, p.name))
        listings.sort(key=lambda x: (x[0] if x[0] is not None else far, x[1].title))
        return Catalog(
            producers=producers, listings=[item for _, item in listings],
            delivery=Delivery(date=self.next_delivery(), window=self.delivery_window()),
            currency=self.config["currency"], logistics_fee=self.config["logistics_fee"],
            free_logistics_from=self.config["free_logistics_from"],
        )

    # ---------- orders: buyer side ----------

    async def place_order(self, data: OrderCreate) -> OrderPlaced:
        wanted: dict[UUID, float] = defaultdict(float)
        for item in data.items:
            wanted[item.listing_id] += item.kg
        today = self.today()
        token = secrets.token_urlsafe(24)
        async with self.session_factory() as session:
            rows = {row[0].id: row for row in await self._on_sale(session, today, True, list(wanted))}
            missing = [str(i) for i in wanted if i not in rows]
            if missing:
                raise InvalidInputError("Some products are no longer available: " + ", ".join(missing))
            parts: dict[UUID, dict] = {}
            latest_from: Optional[date] = None
            for listing_id, kg in wanted.items():
                listing, lot, producer, _, _, state = rows[listing_id]
                now = state["availability"]["kind"] == "now"
                limit = listing.stock_kg if now else listing.weekly_capacity_kg
                if kg > limit + 1e-9:
                    raise InvalidInputError(f"{listing.title}: only {limit:g} kg available.")
                if now:
                    listing.stock_kg = round(listing.stock_kg - kg, 3)
                elif state["available_from"] and (latest_from is None or state["available_from"] > latest_from):
                    latest_from = state["available_from"]
                part = parts.setdefault(producer.id, {"producer": producer, "items": []})
                part["items"].append(OrderItem(
                    listing_id=listing.id, title=listing.title, kg=kg, price_per_kg=listing.price_per_kg,
                    from_stock=now,
                ))
            delivery = self.next_delivery(latest_from)
            pickup = delivery - timedelta(days=self.config["pickup_days_before"])
            subtotal = round(sum(i.kg * i.price_per_kg for p in parts.values() for i in p["items"]), 2)
            logistics = rules.logistics_fee(subtotal, self.config)
            order = Order(
                token_hash=_hash(token), buyer_name=data.buyer.name.strip(), buyer_email=data.buyer.email.lower(),
                buyer_phone=data.buyer.phone, buyer_kind=data.buyer.kind, delivery_address=data.buyer.address.strip(),
                delivery_date=delivery, recurring=data.recurring, subtotal=subtotal, logistics_fee=logistics,
                total=round(subtotal + logistics, 2),
            )
            session.add(order)
            await session.flush()
            created = []
            for p in parts.values():
                gross = round(sum(i.kg * i.price_per_kg for i in p["items"]), 2)
                rate = rules.fee_rate(p["producer"].plan, self.config)
                fee, net = rules.split(gross, rate)
                part = OrderPart(
                    order_id=order.id, account_id=p["producer"].account_id, producer_id=p["producer"].id,
                    status="nuevo", pickup_date=pickup, gross=gross, fee_rate=rate, fee=fee, net=net, packed=[],
                )
                session.add(part)
                await session.flush()
                for item in p["items"]:
                    item.part_id = part.id
                    session.add(item)
                created.append((part, p["producer"], p["items"]))
            await session.commit()
            await session.refresh(order)
        for part, _producer, items in created:
            await self._notify_new(part, order, items)
        read = await self.buyer_order(order.code, token)
        return OrderPlaced(**read.model_dump(), token=token)

    async def _notify_new(self, part: OrderPart, order: Order, items: list[OrderItem]) -> None:
        what = ", ".join(f"{i.title} {i.kg:g} kg" for i in items)
        try:
            await self.notifications.notify_account(
                account_id=part.account_id, exclude_user_id=None, type="market_order",
                title=f"Pedido nuevo #{order.code}", message=f"{order.buyer_name}: {what}. Aceptalo para prepararlo.",
                entity_type="market_order", entity_id=part.id,
            )
        except Exception:  # noqa: BLE001 - the order is placed; the panel shows it anyway
            logger.exception("Could not notify the new market order %s", order.code)

    async def buyer_order(self, code: int, token: str) -> BuyerOrderRead:
        async with self.session_factory() as session:
            order = (await session.execute(select(Order).where(Order.code == code))).scalar_one_or_none()
            if order is None or not hmac.compare_digest(order.token_hash, _hash(token)):
                raise NotFoundError("Order not found.")
            rows = (await session.execute(
                select(OrderPart, Producer.display_name).join(Producer, Producer.id == OrderPart.producer_id)
                .where(OrderPart.order_id == order.id)
            )).all()
            items = await self._items(session, [part.id for part, _ in rows])
        parts, statuses = [], []
        for part, name in rows:
            its = items.get(part.id, [])
            parts.append(BuyerPartRead(producer_name=name, status=part.status, items=its,
                                       subtotal=round(sum(i.total for i in its), 2)))
            statuses.append(part.status)
        live = [p for p in parts if p.status != "rechazado"]
        subtotal = round(sum(p.subtotal for p in live), 2)
        # The logistics fee was quoted when ordering; a producer dropping out never makes it dearer.
        logistics = min(order.logistics_fee, rules.logistics_fee(subtotal, self.config))
        return BuyerOrderRead(
            code=order.code, buyer_name=order.buyer_name, buyer_email=order.buyer_email,
            delivery_address=order.delivery_address, delivery_date=order.delivery_date,
            delivery_window=self.delivery_window(), recurring=order.recurring, status=self._buyer_status(statuses),
            parts=parts, subtotal=subtotal, logistics_fee=logistics, total=round(subtotal + logistics, 2),
            created_at=order.created_at,
        )

    @staticmethod
    def _buyer_status(statuses: list[str]) -> str:
        live = [s for s in statuses if s != "rechazado"]
        if not live:
            return "cancelado"
        if all(s == "entregado" for s in live):
            return "entregado"
        if all(s in ("listo", "entregado") for s in live):
            return "en_camino"
        if any(s != "nuevo" for s in live):
            return "en_preparacion"
        return "recibido"

    async def _items(self, session: AsyncSession, part_ids: list[UUID]) -> dict[UUID, list[OrderItemRead]]:
        out: dict[UUID, list[OrderItemRead]] = defaultdict(list)
        if not part_ids:
            return out
        rows = (await session.execute(
            select(OrderItem).where(OrderItem.part_id.in_(part_ids)).order_by(OrderItem.title)
        )).scalars()
        for i in rows:
            out[i.part_id].append(OrderItemRead(title=i.title, kg=i.kg, price_per_kg=i.price_per_kg,
                                                total=round(i.kg * i.price_per_kg, 2), from_stock=i.from_stock))
        return out

    # ---------- orders: producer side ----------

    def _producer_read(self, part: OrderPart, order: Order, items: list[OrderItemRead]) -> ProducerOrderRead:
        packed = set(part.packed or [])
        boxes = rules.boxes(order.code, ((i.title, i.kg) for i in items))
        return ProducerOrderRead(
            id=part.id, code=order.code, buyer_name=order.buyer_name, buyer_kind=order.buyer_kind,
            status=part.status, pickup_date=part.pickup_date, delivery_date=order.delivery_date, items=items,
            boxes=[{**b, "packed": b["code"] in packed or part.status in ("listo", "entregado")} for b in boxes],
            gross=part.gross, fee_rate=part.fee_rate, fee=part.fee, net=part.net, reject_reason=part.reject_reason,
            accepted_at=part.accepted_at, ready_at=part.ready_at, delivered_at=part.delivered_at,
            created_at=part.created_at,
        )

    async def _parts(self, session: AsyncSession, account_id: UUID, *conditions) -> list[ProducerOrderRead]:
        rows = (await session.execute(
            select(OrderPart, Order).join(Order, Order.id == OrderPart.order_id)
            .where(OrderPart.account_id == account_id, *conditions)
            .order_by(OrderPart.pickup_date, Order.code.desc())
        )).all()
        items = await self._items(session, [part.id for part, _ in rows])
        return [self._producer_read(part, order, items.get(part.id, [])) for part, order in rows]

    async def list_orders(self, actor: Actor, scope: str = "active") -> list[ProducerOrderRead]:
        statuses = OPEN_PART_STATUSES if scope == "active" else ("entregado", "rechazado")
        async with self.session_factory() as session:
            parts = await self._parts(session, actor.account_id, OrderPart.status.in_(statuses))
        if scope != "active":
            parts.sort(key=lambda p: p.delivered_at or p.created_at, reverse=True)
        return parts

    async def get_order(self, actor: Actor, part_id: UUID) -> ProducerOrderRead:
        async with self.session_factory() as session:
            parts = await self._parts(session, actor.account_id, OrderPart.id == part_id)
        if not parts:
            raise NotFoundError(f"Order {part_id} not found.")
        return parts[0]

    async def _transition(self, actor: Actor, part_id: UUID, allowed: tuple[str, ...], values: dict,
                          check=None) -> ProducerOrderRead:
        async with self.session_factory() as session:
            part = (await session.execute(
                select(OrderPart).where(OrderPart.id == part_id, OrderPart.account_id == actor.account_id)
                .with_for_update()
            )).scalar_one_or_none()
            if part is None:
                raise NotFoundError(f"Order {part_id} not found.")
            if part.status not in allowed:
                raise InvalidInputError(f"The order is '{part.status}'.")
            if check is not None:
                await check(session, part)
            for key, value in values.items():
                setattr(part, key, value)
            await session.commit()
        return await self.get_order(actor, part_id)

    async def accept(self, actor: Actor, part_id: UUID) -> ProducerOrderRead:
        _require_manager(actor)
        return await self._transition(actor, part_id, ("nuevo",), {"status": "prep", "accepted_at": utcnow()})

    async def reject(self, actor: Actor, part_id: UUID, reason: str) -> ProducerOrderRead:
        """"No llego": the share drops out and what it took from stock goes back."""
        _require_manager(actor)

        async def give_back(session: AsyncSession, part: OrderPart) -> None:
            items = (await session.execute(select(OrderItem).where(OrderItem.part_id == part.id))).scalars()
            for item in items:
                if item.from_stock and item.listing_id:
                    await session.execute(
                        update(Listing).where(Listing.id == item.listing_id)
                        .values(stock_kg=Listing.stock_kg + item.kg)
                    )

        return await self._transition(
            actor, part_id, ("nuevo", "prep"), {"status": "rechazado", "reject_reason": reason.strip()}, give_back
        )

    async def set_packed(self, actor: Actor, part_id: UUID, codes: list[str]) -> ProducerOrderRead:
        current = await self.get_order(actor, part_id)
        valid = {b.code for b in current.boxes}
        unknown = set(codes) - valid
        if unknown:
            raise InvalidInputError("Unknown boxes: " + ", ".join(sorted(unknown)))
        return await self._transition(actor, part_id, ("prep",), {"packed": sorted(set(codes))})

    async def mark_ready(self, actor: Actor, part_id: UUID) -> ProducerOrderRead:
        current = await self.get_order(actor, part_id)
        missing = [b.code for b in current.boxes if not b.packed]
        if current.status == "prep" and missing:
            raise InvalidInputError(f"{len(missing)} boxes still to pack.")
        return await self._transition(actor, part_id, ("prep",), {"status": "listo", "ready_at": utcnow()})

    # ---------- the producer's panel ----------

    async def dashboard(self, actor: Actor) -> Dashboard:
        today = self.today()
        month_start = today.replace(day=1)
        tz = ZoneInfo(self.tz)
        since = datetime.combine(month_start, time.min, tz)
        async with self.session_factory() as session:
            producer = await self._my_producer(session, actor)
            active = await self._parts(session, actor.account_id, OrderPart.status.in_(OPEN_PART_STATUSES))
            delivered = await self._parts(
                session, actor.account_id, OrderPart.status == "entregado", OrderPart.delivered_at >= since
            )
            route = await self._route_for(session, producer, today)
            currency = (await session.execute(
                select(Account.currency).where(Account.id == actor.account_id)
            )).scalar_one_or_none()
        gross = round(sum(p.gross for p in delivered), 2)
        boxes_total = sum(len(p.boxes) for p in active)
        boxes_ready = sum(sum(1 for b in p.boxes if b.packed) for p in active)
        delivered.sort(key=lambda p: p.delivered_at, reverse=True)
        sales = [
            SaleRow(code=p.code, delivered_on=p.delivered_at.astimezone(tz).date(), buyer_name=p.buyer_name,
                    kg=round(sum(i.kg for i in p.items), 2), gross=p.gross, fee=p.fee, net=p.net)
            for p in delivered
        ]
        return Dashboard(
            producer=ProducerRead.model_validate(producer), month_label=MONTHS[today.month - 1],
            month_sales=gross, month_orders=len(delivered),
            settlement_date=rules.next_weekday(today, self.config["settlement_weekday"]),
            to_collect=round(sum(p.net for p in active), 2),
            active_orders=len(active), active_kg=round(sum(i.kg for p in active for i in p.items), 2),
            boxes_total=boxes_total, boxes_ready=boxes_ready, route=route, sales=sales,
            plan_month=PlanMonth(**rules.plan_month(gross, producer.plan, self.config)),
            currency=currency or self.config["currency"],
        )

    async def _route_for(self, session: AsyncSession, producer: Producer, today: date) -> Optional[TodayRoute]:
        """Today's route if it stops here, else the next one that does."""
        route = (await session.execute(
            select(PickupRoute).join(PickupStop, PickupStop.route_id == PickupRoute.id)
            .where(PickupStop.producer_id == producer.id, PickupRoute.route_date >= today)
            .order_by(PickupRoute.route_date).limit(1)
        )).scalar_one_or_none()
        if route is None:
            return None
        stops = (await session.execute(
            select(PickupStop, Producer.display_name).join(Producer, Producer.id == PickupStop.producer_id)
            .where(PickupStop.route_id == route.id).order_by(PickupStop.position)
        )).all()
        reads = [
            RouteStopRead(producer_name=name, eta=stop.eta, is_me=stop.producer_id == producer.id,
                          picked_up=stop.picked_up_at is not None)
            for stop, name in stops
        ]
        mine = next((s.eta for s in reads if s.is_me), None)
        return TodayRoute(
            id=route.id, route_date=route.route_date, name=route.name, driver_name=route.driver_name, my_eta=mine,
            stops=reads, hub_name=route.hub_name, hub_eta=route.hub_eta, deliveries_from=route.deliveries_from,
        )

    # ---------- the network's operators (platform admins) ----------

    async def list_producers(self) -> list[ProducerRead]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(Producer).order_by(Producer.display_name))).scalars().all()
        return [ProducerRead.model_validate(p) for p in rows]

    async def set_seal(self, producer_id: UUID, seal_until: Optional[date]) -> ProducerRead:
        async with self.session_factory() as session:
            producer = await session.get(Producer, producer_id)
            if producer is None:
                raise NotFoundError("Producer not found.")
            producer.seal_until = seal_until
            await session.commit()
            await session.refresh(producer)
        return ProducerRead.model_validate(producer)

    async def create_route(self, data: RouteCreate) -> RouteRead:
        async with self.session_factory() as session:
            ids = [s.producer_id for s in data.stops]
            found = set((await session.execute(select(Producer.id).where(Producer.id.in_(ids)))).scalars().all())
            if found != set(ids):
                raise InvalidInputError("Unknown producer in the stops.")
            route = PickupRoute(
                route_date=data.route_date, name=data.name, driver_name=data.driver_name, hub_name=data.hub_name,
                hub_eta=data.hub_eta, deliveries_from=data.deliveries_from,
            )
            session.add(route)
            await session.flush()
            for position, stop in enumerate(sorted(data.stops, key=lambda s: s.eta)):
                session.add(PickupStop(route_id=route.id, producer_id=stop.producer_id, position=position,
                                       eta=stop.eta))
            await session.commit()
            await session.refresh(route)
        return await self._route_read(route.id)

    async def _route_read(self, route_id: UUID) -> RouteRead:
        async with self.session_factory() as session:
            route = await session.get(PickupRoute, route_id)
            stops = (await session.execute(
                select(PickupStop).where(PickupStop.route_id == route_id).order_by(PickupStop.position)
            )).scalars().all()
        return RouteRead(
            id=route.id, route_date=route.route_date, name=route.name, driver_name=route.driver_name,
            hub_name=route.hub_name, stops=[RouteStopIn(producer_id=s.producer_id, eta=s.eta) for s in stops],
        )

    async def list_routes(self, since: date) -> list[RouteRead]:
        async with self.session_factory() as session:
            ids = (await session.execute(
                select(PickupRoute.id).where(PickupRoute.route_date >= since).order_by(PickupRoute.route_date)
            )).scalars().all()
        return [await self._route_read(i) for i in ids]

    async def deliver(self, part_id: UUID) -> None:
        """The driver picked the share up and it reached the buyer: it counts as a sale. Marks the producer's stop on
        that day's route as picked up."""
        async with self.session_factory() as session:
            part = (await session.execute(
                select(OrderPart).where(OrderPart.id == part_id).with_for_update()
            )).scalar_one_or_none()
            if part is None:
                raise NotFoundError("Order part not found.")
            if part.status != "listo":
                raise InvalidInputError(f"The order is '{part.status}', not ready.")
            part.status = "entregado"
            part.delivered_at = utcnow()
            route_ids = select(PickupRoute.id).where(PickupRoute.route_date == part.pickup_date)
            await session.execute(
                update(PickupStop)
                .where(and_(PickupStop.producer_id == part.producer_id, PickupStop.route_id.in_(route_ids),
                            PickupStop.picked_up_at.is_(None)))
                .values(picked_up_at=func.now())
            )
            await session.commit()
