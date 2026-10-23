"""Application records: drafts, confirmation, versioned corrections and voids (see models.py for the rules).

Confirming writes everything a confirmed application implies: the bitácora entry (pest_control / fertilization) so
the log stays one timeline, the stock it consumed, the withholding intervals it learned, the products the registry
didn't have, and each treated lot's "no cosechar hasta" date. A correction or a void undoes and redoes those, and
leaves the previous version in place."""
import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.schemas import FieldEventCreate
from src.application.products.models import normalize_name
from src.application.products.service import ProductRegistryService
from src.application.supplies.service import SupplyService
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import AccountProduct, Application, ApplicationProduct, ProductCropInterval
from .schemas import (
    AccountProductRead,
    ApplicationCorrection,
    ApplicationCreate,
    ApplicationDraftUpdate,
    ApplicationProductIn,
    ApplicationProductRead,
    ApplicationRead,
    ProductIntervalRead,
)

logger = logging.getLogger(__name__)

WEATHER_TIMEOUT_SECONDS = 8
_HEADER_FIELDS = (
    "kind", "applied_at", "target", "method", "equipment", "area_m2", "water_volume_l", "operator_user_id",
    "operator_name", "prescribed_by", "prescription_number", "transcript", "notes", "field_id", "zone_id",
)
_PRODUCT_FIELDS = (
    "kind", "name", "registry_number", "company", "active_ingredients", "formulation", "registry_verified", "dose",
    "dose_unit", "total_quantity", "total_unit", "supply_item_id", "preharvest_interval_days",
    "reentry_interval_hours", "interval_source",
)
_EVENT_TYPE = {"phyto": "pest_control", "biological": "pest_control", "fertilization": "fertilization",
               "other": "pest_control"}


def _fmt(value: Optional[float]) -> str:
    return "" if value is None else f"{value:g}"


def product_line(p) -> str:
    """'Caldo bordelés 20 g/L (2 L)' — how a product reads in the bitácora and the cuaderno."""
    line = p.name
    if p.dose is not None:
        line += f" {_fmt(p.dose)} {p.dose_unit or ''}".rstrip()
    if p.total_quantity is not None:
        line += f" ({_fmt(p.total_quantity)} {p.total_unit or ''})".replace(" )", ")")
    return line


class ApplicationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        farm_service,
        supply_service: SupplyService,
        registry: ProductRegistryService,
        weather_service=None,
        management_service=None,
    ):
        self.session_factory = session_factory
        self.management = management_service
        self.farm = farm_service
        self.supplies = supply_service
        self.registry = registry
        self.weather = weather_service

    # ---------- reads ----------

    async def _versions(self, session: AsyncSession, actor: Actor, record_id: UUID) -> list[Application]:
        rows = (await session.execute(
            select(Application).where(Application.account_id == actor.account_id, Application.record_id == record_id)
            .order_by(Application.version)
        )).scalars().all()
        if not rows:
            raise NotFoundError(f"Application {record_id} not found.")
        return list(rows)

    async def _current(self, session: AsyncSession, actor: Actor, record_id: UUID) -> Application:
        """By record id or by the id of any of its versions."""
        app = await session.get(Application, record_id)
        if app is not None and app.account_id == actor.account_id:
            record_id = app.record_id
        current = [a for a in await self._versions(session, actor, record_id) if a.is_current]
        return current[0]

    async def _products(self, session: AsyncSession, app_ids: list[UUID]) -> dict[UUID, list[ApplicationProduct]]:
        out: dict[UUID, list[ApplicationProduct]] = {i: [] for i in app_ids}
        if app_ids:
            rows = (await session.execute(
                select(ApplicationProduct).where(ApplicationProduct.application_id.in_(app_ids))
                .order_by(ApplicationProduct.position)
            )).scalars()
            for p in rows:
                out[p.application_id].append(p)
        return out

    async def _reads(self, session: AsyncSession, actor: Actor, apps: list[Application]) -> list[ApplicationRead]:
        products = await self._products(session, [a.id for a in apps])
        lot_ids = {lot_id for a in apps for lot_id in a.lot_ids or []}
        labels: dict[UUID, str] = {}
        if lot_ids:
            for lot in await self.farm.list_lots(actor):
                if lot.id in lot_ids:
                    labels[lot.id] = lot.label or str(lot.id)
        out = []
        for app in apps:
            read = ApplicationRead.model_validate(app).model_copy(update={
                "products": [ApplicationProductRead.model_validate(p) for p in products[app.id]],
                "lot_labels": [labels[i] for i in app.lot_ids or [] if i in labels],
            })
            out.append(read.model_copy(update={"warnings": self._warnings(read)}))
        return out

    @staticmethod
    def _warnings(app: ApplicationRead) -> list[str]:
        warnings = []
        if app.applied_at is None:
            warnings.append("Falta la fecha y hora de la aplicación.")
        if not app.products:
            warnings.append("No tiene productos.")
        if not (app.operator_name or app.operator_user_id):
            warnings.append("Falta quién aplicó.")
        for p in app.products:
            if p.dose is None and p.total_quantity is None:
                warnings.append(f"{p.name}: falta la dosis o la cantidad usada.")
            if p.kind in ("phyto", "biological") and p.preharvest_interval_days is None:
                warnings.append(f"{p.name}: falta el período de carencia (leerlo de la etiqueta).")
            if not p.registry_verified and p.kind == "phyto":
                warnings.append(f"{p.name}: no está verificado en el registro.")
        return warnings

    async def list_applications(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[ApplicationRead]:
        stmt = select(Application).where(Application.account_id == actor.account_id, Application.is_current.is_(True))
        if field_id:
            stmt = stmt.where(Application.field_id == field_id)
        if lot_id:
            stmt = stmt.where(Application.lot_ids.any(lot_id))
        if status:
            stmt = stmt.where(Application.status == status)
        if since:
            stmt = stmt.where(Application.applied_at >= since)
        if until:
            stmt = stmt.where(Application.applied_at <= until)
        stmt = stmt.order_by(Application.applied_at.desc().nulls_first(), Application.created_at.desc())
        async with self.session_factory() as session:
            apps = list((await session.execute(stmt.limit(max(1, min(limit, 1000))))).scalars())
            return await self._reads(session, actor, apps)

    async def get(self, actor: Actor, application_id: UUID) -> ApplicationRead:
        async with self.session_factory() as session:
            return (await self._reads(session, actor, [await self._current(session, actor, application_id)]))[0]

    async def history(self, actor: Actor, application_id: UUID) -> list[ApplicationRead]:
        """Every version of the record, oldest first."""
        async with self.session_factory() as session:
            current = await self._current(session, actor, application_id)
            return await self._reads(session, actor, await self._versions(session, actor, current.record_id))

    async def account_products(self, actor: Actor, query: Optional[str] = None) -> list[AccountProductRead]:
        stmt = select(AccountProduct).where(AccountProduct.account_id == actor.account_id)
        if query:
            stmt = stmt.where(AccountProduct.name_norm.ilike(f"%{normalize_name(query)}%"))
        async with self.session_factory() as session:
            rows = (await session.execute(stmt.order_by(AccountProduct.name))).scalars()
            return [AccountProductRead.model_validate(r) for r in rows]

    async def intervals(self, actor: Actor, product: Optional[str] = None) -> list[ProductIntervalRead]:
        stmt = select(ProductCropInterval).where(ProductCropInterval.account_id == actor.account_id)
        if product:
            stmt = stmt.where(ProductCropInterval.product_norm.ilike(f"%{normalize_name(product)}%"))
        async with self.session_factory() as session:
            rows = (await session.execute(stmt.order_by(ProductCropInterval.product_name))).scalars()
            return [ProductIntervalRead.model_validate(r) for r in rows]

    # ---------- writes ----------

    async def _scope(self, actor: Actor, field_id: UUID, zone_id: Optional[UUID], lot_ids: list[UUID]) -> list[UUID]:
        await self.farm.get_field(actor, field_id)
        if zone_id:
            zone = await self.farm.get_zone(actor, zone_id)
            if zone.field_id != field_id:
                raise InvalidInputError("That zone is not in that field.")
        if lot_ids:
            for lot_id in lot_ids:
                if (await self.farm.get_lot(actor, lot_id)).field_id != field_id:
                    raise InvalidInputError("A lot does not belong to that field.")
            return list(dict.fromkeys(lot_ids))
        return await self.farm.reached_lots(actor, field_id, zone_id)

    async def _crop_names(self, actor: Actor, lot_ids: list[UUID]) -> list[str]:
        names = []
        for lot_id in lot_ids:
            lot = await self.farm.get_lot(actor, lot_id)
            names.append((await self.farm.get_crop_master(actor, lot.crop_master_id)).name)
        return list(dict.fromkeys(names))

    async def _product_rows(
        self, session: AsyncSession, actor: Actor, products: list[ApplicationProductIn], crops: list[str]
    ) -> list[ApplicationProduct]:
        rows = []
        for position, product in enumerate(products):
            values: dict[str, Any] = product.model_dump()
            if product.supply_item_id:
                item = await self.supplies.item_in_session(session, actor, product.supply_item_id)
                for key in ("name", "registry_number", "company", "active_ingredients", "formulation"):
                    values[key] = values[key] or getattr(item, key)
            values["registry_verified"] = await self.registry.verify(
                values["name"], values["registry_number"], actor.country
            )
            if values["registry_verified"] and not (values["registry_number"] and values["active_ingredients"]):
                match = await self.registry.search(values["registry_number"] or values["name"], actor.country, limit=1)
                if match:
                    values["registry_number"] = values["registry_number"] or match[0].registry_number
                    values["company"] = values["company"] or match[0].company
                    values["active_ingredients"] = values["active_ingredients"] or match[0].active_ingredients
            if product.preharvest_interval_days is not None or product.reentry_interval_hours is not None:
                values["interval_source"] = product.interval_source or "user"
            else:
                saved = await self._saved_interval(session, actor, values["name"], crops)
                if saved is not None:
                    values.update(saved, interval_source="saved")
                else:
                    values["interval_source"] = "none"
            rows.append(ApplicationProduct(position=position, **values))
        return rows

    async def _saved_interval(
        self, session: AsyncSession, actor: Actor, product: str, crops: list[str]
    ) -> Optional[dict]:
        """The longest interval saved for that product on any of the treated crops, when every crop has one."""
        if not crops:
            return None
        rows = (await session.execute(select(ProductCropInterval).where(
            ProductCropInterval.account_id == actor.account_id,
            ProductCropInterval.product_norm == normalize_name(product),
            ProductCropInterval.crop_norm.in_([normalize_name(c) for c in crops]),
        ))).scalars().all()
        if len(rows) < len(crops):
            return None
        days = [r.preharvest_interval_days for r in rows if r.preharvest_interval_days is not None]
        hours = [r.reentry_interval_hours for r in rows if r.reentry_interval_hours is not None]
        return {
            "preharvest_interval_days": max(days) if days else None,
            "reentry_interval_hours": max(hours) if hours else None,
        }

    async def create_draft(
        self, actor: Actor, data: ApplicationCreate, source: Optional[str] = None
    ) -> ApplicationRead:
        lot_ids = await self._scope(actor, data.field_id, data.zone_id, data.lot_ids)
        crops = await self._crop_names(actor, lot_ids)
        async with self.session_factory() as session:
            app = Application(
                account_id=actor.account_id, record_id=uuid.uuid4(), version=1, is_current=True, status="draft",
                lot_ids=lot_ids, evidence=[e.model_dump() for e in data.evidence], recorded_by=actor.user_id,
                source=source or ("agent" if actor.via == "agent" else "user"),
                **data.model_dump(exclude={"lot_ids", "products", "evidence"}),
            )
            session.add(app)
            await session.flush()
            for row in await self._product_rows(session, actor, data.products, crops):
                row.application_id = app.id
                session.add(row)
            await session.commit()
            return (await self._reads(session, actor, [app]))[0]

    def _check_author(self, actor: Actor, app: Application) -> None:
        if not actor.is_manager and app.recorded_by != actor.user_id:
            raise PermissionDeniedError("Only owner, tecnico or whoever recorded it can change this application.")

    async def update_draft(self, actor: Actor, application_id: UUID, data: ApplicationDraftUpdate) -> ApplicationRead:
        async with self.session_factory() as session:
            app = await self._current(session, actor, application_id)
            if app.status != "draft":
                raise InvalidInputError("A confirmed application is not edited: correct it (a new version) instead.")
            self._check_author(actor, app)
            await self._apply_changes(session, actor, app, data)
            await session.commit()
            return (await self._reads(session, actor, [app]))[0]

    async def _apply_changes(
        self, session: AsyncSession, actor: Actor, app: Application, data: ApplicationDraftUpdate
    ) -> None:
        values = data.model_dump(exclude_unset=True, exclude={"products", "lot_ids", "evidence", "reason"})
        for key, value in values.items():
            setattr(app, key, value)
        if data.evidence is not None:
            app.evidence = [e.model_dump() for e in data.evidence]
        if "lot_ids" in data.model_fields_set or "zone_id" in values:
            app.lot_ids = await self._scope(actor, app.field_id, app.zone_id, data.lot_ids or [])
        if data.products is not None:
            crops = await self._crop_names(actor, app.lot_ids or [])
            for old in (await self._products(session, [app.id]))[app.id]:
                await session.delete(old)
            for row in await self._product_rows(session, actor, data.products, crops):
                row.application_id = app.id
                session.add(row)

    async def delete_draft(self, actor: Actor, application_id: UUID) -> None:
        """Only a draft goes away: a confirmed record is voided, never deleted."""
        async with self.session_factory() as session:
            app = await self._current(session, actor, application_id)
            if app.status != "draft" or app.version != 1:
                raise InvalidInputError("Only a draft can be deleted; a confirmed application is voided instead.")
            self._check_author(actor, app)
            await session.delete(app)
            await session.commit()

    async def _weather_at(self, actor: Actor, field_id: UUID, when: datetime) -> Optional[dict]:
        if self.weather is None:
            return None
        field = await self.farm.get_field(actor, field_id)
        if field.latitude is None or field.longitude is None:
            return None
        try:
            return await asyncio.wait_for(
                self.weather.conditions_at(field.latitude, field.longitude, when), WEATHER_TIMEOUT_SECONDS
            )
        except Exception as e:  # noqa: BLE001 - the record stands without it
            logger.warning(f"No weather for application at {when}: {type(e).__name__}")
            return None

    def _derived(self, actor: Actor, app: Application, products: list[ApplicationProduct]) -> None:
        tz = ZoneInfo(actor.timezone) if actor.timezone else None
        days = [p.preharvest_interval_days for p in products if p.preharvest_interval_days is not None]
        hours = [p.reentry_interval_hours for p in products if p.reentry_interval_hours is not None]
        applied_day = app.applied_at.astimezone(tz).date() if tz else app.applied_at.date()
        app.harvest_release_date = applied_day + timedelta(days=max(days)) if days else None
        app.reentry_until = app.applied_at + timedelta(hours=max(hours)) if hours else None

    async def _effects(
        self, session: AsyncSession, actor: Actor, app: Application, products: list[ApplicationProduct], sign: int,
        reason: str,
    ) -> None:
        """Stock in (sign -1) or out (+1) for the products taken from stock."""
        for p in products:
            if p.supply_item_id and p.total_quantity:
                await self.supplies.consume_for_application(
                    session, actor, p.supply_item_id, sign * p.total_quantity, p.total_unit or "", app.id, reason
                )

    async def _learn(self, session: AsyncSession, actor: Actor, app: Application,
                     products: list[ApplicationProduct]) -> None:
        """Keep the intervals read on the labels, and the products the registry doesn't have."""
        crops = await self._crop_names(actor, app.lot_ids or [])
        for p in products:
            if p.interval_source in ("label", "user") and crops:
                for crop in crops:
                    key = (actor.account_id, normalize_name(p.name), normalize_name(crop))
                    row = (await session.execute(select(ProductCropInterval).where(
                        ProductCropInterval.account_id == key[0], ProductCropInterval.product_norm == key[1],
                        ProductCropInterval.crop_norm == key[2],
                    ))).scalar_one_or_none()
                    if row is None:
                        row = ProductCropInterval(account_id=key[0], product_norm=key[1], crop_norm=key[2],
                                                  product_name=p.name, crop_name=crop)
                        session.add(row)
                    row.preharvest_interval_days = p.preharvest_interval_days
                    row.reentry_interval_hours = p.reentry_interval_hours
                    row.source = p.interval_source
                    row.updated_by = actor.user_id
            if not p.registry_verified:
                exists = (await session.execute(select(AccountProduct.id).where(
                    AccountProduct.account_id == actor.account_id, AccountProduct.name_norm == normalize_name(p.name)
                ))).first()
                if not exists:
                    session.add(AccountProduct(
                        account_id=actor.account_id, kind=p.kind, name=p.name, name_norm=normalize_name(p.name),
                        registry_number=p.registry_number, company=p.company,
                        active_ingredients=p.active_ingredients, formulation=p.formulation,
                        created_by=actor.user_id,
                    ))

    def _event_notes(self, app: Application, products: list[ApplicationProduct]) -> str:
        notes = "; ".join(product_line(p) for p in products)
        if app.target:
            notes += f" — {app.target}"
        return notes

    async def confirm(self, actor: Actor, application_id: UUID) -> ApplicationRead:
        async with self.session_factory() as session:
            app = await self._current(session, actor, application_id)
            if app.status != "draft":
                raise InvalidInputError("Only a draft is confirmed.")
            self._check_author(actor, app)
            products = (await self._products(session, [app.id]))[app.id]
            missing = []
            if app.applied_at is None:
                missing.append("la fecha y hora")
            if not products:
                missing.append("al menos un producto")
            if any(p.dose is None and p.total_quantity is None for p in products):
                missing.append("la dosis o la cantidad de cada producto")
            if not (app.operator_name or app.operator_user_id):
                missing.append("quién aplicó")
            if missing:
                raise InvalidInputError("To confirm it, the record still needs: " + ", ".join(missing) + ".")
            event = await self.farm.create_event(actor, FieldEventCreate(
                field_id=app.field_id, zone_id=app.zone_id, lot_ids=list(app.lot_ids or []),
                type=_EVENT_TYPE[app.kind], occurred_at=app.applied_at, notes=self._event_notes(app, products),
                data={"application_record_id": str(app.record_id)},
            ))
            try:
                app.weather = await self._weather_at(actor, app.field_id, app.applied_at)
                self._derived(actor, app, products)
                app.status, app.confirmed_by, app.confirmed_at = "confirmed", actor.user_id, utcnow()
                app.field_event_id = event.id
                await self._effects(session, actor, app, products, 1, f"Aplicación del {app.applied_at.date()}")
                await self._learn(session, actor, app, products)
                await session.commit()
            except Exception:
                await self.farm.repo.delete_event(actor.account_id, event.id)
                raise
            read = (await self._reads(session, actor, [app]))[0]
        await self.refresh_withholding(actor, read.lot_ids)
        return read

    async def _new_version(
        self, session: AsyncSession, actor: Actor, current: Application, status: str, reason: str
    ) -> tuple[Application, list[ApplicationProduct], list[ApplicationProduct]]:
        old_products = (await self._products(session, [current.id]))[current.id]
        current.is_current = False
        await session.flush()
        new = Application(
            id=uuid.uuid4(), record_id=current.record_id, version=current.version + 1, is_current=True,
            supersedes_id=current.id, correction_reason=reason, account_id=current.account_id, status=status,
            lot_ids=list(current.lot_ids or []), evidence=list(current.evidence or []), weather=current.weather,
            source=current.source, field_event_id=current.field_event_id, recorded_by=actor.user_id,
            confirmed_by=actor.user_id, confirmed_at=utcnow(),
            **{k: getattr(current, k) for k in _HEADER_FIELDS},
        )
        session.add(new)
        await session.flush()
        copies = []
        for p in old_products:
            copy = ApplicationProduct(application_id=new.id, position=p.position,
                                      **{k: getattr(p, k) for k in _PRODUCT_FIELDS})
            session.add(copy)
            copies.append(copy)
        await session.flush()
        return new, old_products, copies

    async def correct(self, actor: Actor, application_id: UUID, data: ApplicationCorrection) -> ApplicationRead:
        """A new version of a confirmed record: the changes plus their reason. Stock and the bitácora follow."""
        async with self.session_factory() as session:
            current = await self._current(session, actor, application_id)
            if current.status != "confirmed":
                raise InvalidInputError("Only a confirmed application is corrected (a draft is just edited).")
            self._check_author(actor, current)
            before_lots = list(current.lot_ids or [])
            new, old_products, _ = await self._new_version(session, actor, current, "confirmed", data.reason)
            await self._apply_changes(session, actor, new, data)
            await session.flush()
            products = (await self._products(session, [new.id]))[new.id]
            self._derived(actor, new, products)
            if "applied_at" in data.model_fields_set:
                new.weather = await self._weather_at(actor, new.field_id, new.applied_at)
            await self._effects(session, actor, current, old_products, -1, f"Corrección v{new.version}: devolución")
            await self._effects(session, actor, new, products, 1, f"Corrección v{new.version}")
            await self._learn(session, actor, new, products)
            event_values = {"occurred_at": new.applied_at, "notes": self._event_notes(new, products),
                            "type": _EVENT_TYPE[new.kind], "zone_id": new.zone_id}
            await session.commit()
            read = (await self._reads(session, actor, [new]))[0]
        if read.field_event_id:  # after the commit: its row is referenced by the versions just written
            await self.farm.repo.update_event(actor.account_id, read.field_event_id, event_values,
                                              lot_ids=list(read.lot_ids))
        await self.refresh_withholding(actor, list(set(before_lots) | set(read.lot_ids)))
        return read

    async def void(self, actor: Actor, application_id: UUID, reason: str) -> ApplicationRead:
        """It didn't happen (recorded by mistake): a last version says so. Stock comes back, the bitácora entry
        stays marked as voided (skipped, with the reason); every earlier version stays."""
        async with self.session_factory() as session:
            current = await self._current(session, actor, application_id)
            if current.status != "confirmed":
                raise InvalidInputError("Only a confirmed application is voided (a draft is deleted).")
            if not actor.is_manager:
                raise PermissionDeniedError("Only owner or tecnico can void a confirmed application.")
            new, old_products, _ = await self._new_version(session, actor, current, "voided", reason)
            new.harvest_release_date, new.reentry_until = None, None
            await self._effects(session, actor, current, old_products, -1, f"Anulada: {reason}")
            await session.commit()
            read = (await self._reads(session, actor, [new]))[0]
        if read.field_event_id:
            await self.farm.repo.update_event(actor.account_id, read.field_event_id, {
                "outcome": "skipped", "reason": f"Aplicación anulada: {reason}",
            })
        await self.refresh_withholding(actor, read.lot_ids)
        return read

    async def refresh_withholding(self, actor: Actor, lot_ids: list[UUID]) -> None:
        """Each lot's "no cosechar hasta": the latest release date among its confirmed applications in force."""
        if not lot_ids:
            return
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(Application.lot_ids, Application.harvest_release_date).where(
                    Application.account_id == actor.account_id, Application.is_current.is_(True),
                    Application.status == "confirmed", Application.harvest_release_date.is_not(None),
                    Application.lot_ids.overlap(lot_ids),
                )
            )).all()
        until: dict[UUID, Any] = {lot_id: None for lot_id in lot_ids}
        for lots, release in rows:
            for lot_id in lots:
                if lot_id in until and (until[lot_id] is None or release > until[lot_id]):
                    until[lot_id] = release
        for lot_id, release in until.items():
            await self.farm.repo.update_lot(actor.account_id, lot_id, {"harvest_blocked_until": release})

    async def export(
        self, actor: Actor, fmt: str, field_id: Optional[UUID] = None, since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> tuple[bytes, str, str]:
        """(content, media type, file name) of the cuaderno de aplicaciones: confirmed and voided records in force."""
        from .export import to_csv, to_pdf  # fpdf is only needed here

        apps = [a for a in await self.list_applications(actor, field_id=field_id, since=since, until=until, limit=1000)
                if a.status != "draft"]
        apps.sort(key=lambda a: a.applied_at)
        fields = {f.id: f.name for f in await self.farm.list_fields(actor)}
        people = {}
        if self.management is not None:
            for m in await self.management.list_members(actor):
                people[m.id] = " ".join(p for p in (m.first_name, m.last_name) if p) or m.email
        tz = ZoneInfo(actor.timezone) if actor.timezone else None
        stamp = utcnow().astimezone(tz).strftime("%Y%m%d") if tz else utcnow().strftime("%Y%m%d")
        name = f"cuaderno-aplicaciones-{stamp}"
        if fmt == "csv":
            return to_csv(apps, fields, people, tz).encode("utf-8-sig"), "text/csv; charset=utf-8", f"{name}.csv"
        title = "Cuaderno de aplicaciones" + (f" - {fields[field_id]}" if field_id in fields else "")
        period = (since.date() if since else None, until.date() if until else None)
        return to_pdf(apps, fields, people, tz, title, period), "application/pdf", f"{name}.pdf"
