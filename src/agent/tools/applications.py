"""Application records and inputs in stock, from the chat. The agent writes DRAFTS from what the person tells (by
voice or text) and only confirms one when the person said yes to its summary: a confirmed record is an auditable
entry that is never edited again."""
from datetime import timedelta
from typing import Optional
from uuid import UUID

from src.application.applications.schemas import (
    ApplicationCorrection,
    ApplicationCreate,
    ApplicationDraftUpdate,
    ApplicationProductIn,
    Evidence,
)
from src.application.supplies.schemas import SupplyItemCreate, SupplyMovementCreate
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, parse_when, resolve_field, resolve_zone, tool

_ME = {"yo", "me", "mi", "mí", "self", "i"}


def _summary(app) -> dict:
    return compact({
        "id": str(app.id), "record_id": str(app.record_id), "version": app.version, "status": app.status,
        "applied_at": app.applied_at, "lots": app.lot_labels, "target": app.target,
        "followup_id": app.followup_id and str(app.followup_id),
        "products": [
            {"name": p.name, "registry_number": p.registry_number, "registered": p.registry_verified,
             "dose": p.dose, "dose_unit": p.dose_unit, "total": p.total_quantity, "total_unit": p.total_unit,
             "withholding_days": p.preharvest_interval_days, "withholding_source": p.interval_source}
            for p in app.products
        ],
        "operator": app.operator_name or (str(app.operator_user_id) if app.operator_user_id else None),
        "harvest_release_date": app.harvest_release_date, "weather": app.weather,
        "missing_or_warnings": app.warnings,
    })


def _products(items: Optional[list[dict]]) -> Optional[list[ApplicationProductIn]]:
    if items is None:
        return None
    out = []
    for item in items:
        values = dict(item)
        if values.get("preharvest_interval_days") is not None and not values.get("interval_source"):
            values["interval_source"] = "label"
        out.append(ApplicationProductIn(**values))
    return out


def application_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    def _operator(operator: Optional[str]) -> dict:
        if not operator:
            return {}
        if operator.strip().lower() in _ME:
            return {"operator_user_id": ctx.actor.user_id}
        try:
            return {"operator_user_id": UUID(operator)}
        except ValueError:
            return {"operator_name": operator.strip()}

    async def _open_followups_here(app) -> list[dict]:
        """The open follow-ups where it was applied, when it isn't linked to one: the agent asks whether it was
        for one of them (the treatment then joins that follow-up's history)."""
        if app.followup_id or deps.followups is None:
            return []
        lots = {str(i) for i in app.lot_ids}
        return [
            {"followup_id": str(f.id), "title": f.title, "since": f.created_at.date()}
            for f in await deps.followups.list_followups(ctx.actor, field_id=app.field_id, status="abierto")
            if (app.zone_id and f.zone_id == app.zone_id) or lots & {str(i) for i in f.lot_ids}
            or not (app.zone_id or lots)
        ]

    def _evidence(attach_current_photo: bool) -> list[Evidence]:
        evidence = []
        if attach_current_photo:
            if not ctx.image_identifier:
                raise InvalidInputError("There is no photo in this message to attach.")
            evidence.append(Evidence(kind="photo", identifier=ctx.image_identifier, note="foto del turno"))
        if ctx.audio_identifier:
            evidence.append(Evidence(kind="audio", identifier=ctx.audio_identifier, note="audio del turno"))
        return evidence

    @tool
    async def find_product(query: str, kind: Optional[str] = None) -> dict:
        """Find a product by brand or registry number in the official registry of the user's country (SENASA in
        Argentina: phytosanitaries and fertilizers) and in the account's own products. Returns its formal text to
        copy into an application or a stock item. Being registered is NOT being authorised for a crop, and the
        registry has no withholding periods: those come from the label. kind: phyto | fertilizer."""
        registered = await deps.registry.search(query, ctx.actor.country, kind=kind, limit=8)
        own = await deps.applications.account_products(ctx.actor, query)
        stock = await deps.supplies.list_items(ctx.actor, query=query)
        return {
            "registered": compact(registered),
            "account_products_not_in_registry": compact(own),
            "in_stock": [compact({"supply_item_id": str(i.id), "name": i.name, "quantity": i.quantity,
                                  "unit": i.unit, "expiry_date": i.expiry_date}) for i in stock],
        }

    @tool
    async def record_application(
        products: list[dict],
        field: Optional[str] = None,
        zone: Optional[str] = None,
        lots: Optional[list[str]] = None,
        applied_at: Optional[str] = None,
        target: Optional[str] = None,
        followup_id: Optional[str] = None,
        operator: Optional[str] = None,
        kind: str = "phyto",
        method: Optional[str] = None,
        area_m2: Optional[float] = None,
        water_volume_l: Optional[float] = None,
        prescribed_by: Optional[str] = None,
        transcript: Optional[str] = None,
        notes: Optional[str] = None,
        attach_current_photo: bool = False,
    ) -> dict:
        """Write a DRAFT application record from what the person tells ("apliqué 2 cc por litro de X en los tomates
        del cantero 2 contra tizón"). A phytosanitary, biological or fertilizer application goes here, not in
        log_events. Nothing is in the record until it is confirmed.
        - products: [{name, registry_number?, active_ingredients?, kind?: phyto|fertilizer|amendment|biological|
          other, dose?, dose_unit? ('cc/L', 'g/10 L', 'L/ha'), total_quantity?, total_unit? ('ml','l','g','kg'),
          supply_item_id? (from find_product: discounts stock), preharvest_interval_days?, reentry_interval_hours?}].
          Use find_product first to copy the registered name and number. A product not in the registry is written as
          said. NEVER fill preharvest_interval_days from your own knowledge: only from the label (photo) or what the
          person says; if missing, a saved one for that product and crop is reused, else it stays empty and you ask.
        - where: lots (ids), or zone ('cantero 2': every lot growing there), or neither (the whole field).
        - applied_at: ISO date/time (default now). operator: 'yo' (the person writing), a member id or a name.
        - kind: phyto | fertilization | biological | other. transcript: what they dictated, word for word, if audio.
        - target: what it was for (the pest, disease or reason). followup_id: the open follow-up (seguimiento) it
          treats, from list_followups — the treatment then joins that problem's history. If the result lists
          open_followups_here and the target matches one, link it (update_application_draft) or ask which.
        Then show the person a SHORT summary (products and doses, lots, date, who, withholding and harvest date,
        what is missing) and ask them to confirm; call confirm_application only after their yes."""
        target_field = await resolve_field(deps, ctx, field)
        zone_id = (await resolve_zone(deps, ctx, target_field, zone)).id if zone else None
        draft = await deps.applications.create_draft(ctx.actor, ApplicationCreate(
            field_id=target_field.id, zone_id=zone_id, lot_ids=[UUID(str(lot)) for lot in lots or []],
            applied_at=parse_when(applied_at, ctx.tz) or utcnow(), target=target, kind=kind, method=method,
            followup_id=UUID(followup_id) if followup_id else None,
            area_m2=area_m2, water_volume_l=water_volume_l, prescribed_by=prescribed_by, transcript=transcript,
            notes=notes, evidence=_evidence(attach_current_photo), products=_products(products) or [],
            **_operator(operator),
        ), source="agent")
        return compact({"draft": _summary(draft), "open_followups_here": await _open_followups_here(draft),
                        "next": "Show the summary and ask the person to confirm it."})

    @tool
    async def update_application_draft(
        application_id: str,
        products: Optional[list[dict]] = None,
        applied_at: Optional[str] = None,
        target: Optional[str] = None,
        followup_id: Optional[str] = None,
        operator: Optional[str] = None,
        lots: Optional[list[str]] = None,
        method: Optional[str] = None,
        area_m2: Optional[float] = None,
        water_volume_l: Optional[float] = None,
        prescribed_by: Optional[str] = None,
        notes: Optional[str] = None,
        attach_current_photo: bool = False,
    ) -> dict:
        """Fix or complete a DRAFT before it is confirmed (products replaces the whole list, same shape as in
        record_application). A confirmed record is corrected with correct_application instead."""
        values = {"target": target, "method": method, "area_m2": area_m2, "water_volume_l": water_volume_l,
                  "prescribed_by": prescribed_by, "notes": notes, "applied_at": parse_when(applied_at, ctx.tz),
                  "products": _products(products), **_operator(operator)}
        values = {k: v for k, v in values.items() if v is not None}
        if followup_id:
            values["followup_id"] = UUID(followup_id)
        if lots is not None:
            values["lot_ids"] = [UUID(str(lot)) for lot in lots]
        if attach_current_photo:
            current = await deps.applications.get(ctx.actor, UUID(application_id))
            values["evidence"] = [*current.evidence, *_evidence(True)]
        draft = await deps.applications.update_draft(ctx.actor, UUID(application_id), ApplicationDraftUpdate(**values))
        return {"draft": _summary(draft)}

    @tool
    async def confirm_application(application_id: str) -> dict:
        """Confirm a draft into the record: ONLY after the person said yes to its summary in a message of their own.
        It writes the bitácora entry, discounts the stock it used and sets "no cosechar hasta" on the treated lots.
        From then on it is never edited: changes are corrections with a reason."""
        confirmed = await deps.applications.confirm(ctx.actor, UUID(application_id))
        return {"confirmed": _summary(confirmed)}

    @tool
    async def link_application_to_followup(application_id: str, followup_id: Optional[str] = None) -> dict:
        """Say which follow-up (seguimiento) an application treats — a draft or an already confirmed one, without a
        correction: it's context, not what was applied ("lo del jabón potásico era para el pulgón"). Its bitácora
        entry joins that problem's history. followup_id empty: unlink."""
        linked = await deps.applications.link_followup(
            ctx.actor, UUID(application_id), UUID(followup_id) if followup_id else None
        )
        return {"application": _summary(linked)}

    @tool
    async def correct_application(
        application_id: str, reason: str, products: Optional[list[dict]] = None, applied_at: Optional[str] = None,
        target: Optional[str] = None, operator: Optional[str] = None, lots: Optional[list[str]] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Correct a CONFIRMED record: a new version with the reason ("eran 300 ml, no 200"); the previous one stays
        in its history. Only after the person confirmed the change."""
        values = {"target": target, "notes": notes, "applied_at": parse_when(applied_at, ctx.tz),
                  "products": _products(products), **_operator(operator)}
        values = {k: v for k, v in values.items() if v is not None}
        if lots is not None:
            values["lot_ids"] = [UUID(str(lot)) for lot in lots]
        fixed = await deps.applications.correct(
            ctx.actor, UUID(application_id), ApplicationCorrection(reason=reason, **values)
        )
        return {"corrected": _summary(fixed)}

    @tool
    async def list_applications(
        field: Optional[str] = None, lot_id: Optional[str] = None, days: int = 60, status: Optional[str] = None
    ) -> dict:
        """The application records in force (drafts included unless status filters): what was applied to a lot or a
        field, with doses, withholding and harvest release dates. Answers "¿qué se le aplicó?", "¿puedo cosechar?"."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        apps = await deps.applications.list_applications(
            ctx.actor, field_id=field_id, lot_id=UUID(lot_id) if lot_id else None, status=status,
            since=utcnow() - timedelta(days=max(1, min(days, 730))), limit=50,
        )
        return {"applications": [_summary(a) for a in apps]}

    @tool
    async def list_supplies(query: Optional[str] = None, kind: Optional[str] = None,
                            in_stock: Optional[bool] = None, expiring_within_days: Optional[int] = None) -> dict:
        """Inputs in stock (phytosanitaries, fertilizers, amendments, substrates, biologicals; seeds are in
        list_seed_inventory): quantity, unit, expiry. kind: phyto|fertilizer|amendment|substrate|biological|other."""
        items = await deps.supplies.list_items(ctx.actor, query=query, kind=kind, in_stock=in_stock,
                                               expiring_within_days=expiring_within_days)
        return {"supplies": compact(items)}

    @tool
    async def receive_supply(
        name: str, kind: str, quantity: float, unit: str, registry_number: Optional[str] = None,
        active_ingredients: Optional[str] = None, company: Optional[str] = None,
        manufacturer_lot: Optional[str] = None, expiry_date: Optional[str] = None,
        supply_item_id: Optional[str] = None, attach_current_photo: bool = False, notes: Optional[str] = None,
    ) -> dict:
        """Something came in ("llegaron 2 bidones de 5 L de X", a photo of the remito or the label). With
        supply_item_id: more of an item already in stock. Otherwise a new item, written as on the label (use
        find_product to copy the registered name and number). unit: l | ml | kg | g | unidad."""
        image = None
        if attach_current_photo:
            if not ctx.image_identifier:
                raise InvalidInputError("There is no photo in this message to attach.")
            image = ctx.image_identifier
        if supply_item_id:
            item = await deps.supplies.add_movement(ctx.actor, UUID(supply_item_id), SupplyMovementCreate(
                kind="receipt", quantity=quantity, unit=unit, reason=notes, image_identifier=image,
            ))
        else:
            item = await deps.supplies.create_item(ctx.actor, SupplyItemCreate(
                kind=kind, name=name, quantity=quantity, unit=unit, registry_number=registry_number,
                active_ingredients=active_ingredients, company=company, manufacturer_lot=manufacturer_lot,
                expiry_date=expiry_date, notes=notes, image_identifier=image,
            ))
        return {"supply": compact(item)}

    return [
        find_product, record_application, update_application_draft, confirm_application, correct_application,
        link_application_to_followup, list_applications, list_supplies, receive_supply,
    ]
