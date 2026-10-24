from datetime import timedelta
from typing import Optional
from uuid import UUID

from src.application.farm.schemas import (
    LotCreate,
    LotUpdate,
    CropMasterCreate,
    FieldCreate,
    FieldEventCreate,
    FieldUpdate,
    FieldZoneCreate,
    LayoutObject,
)
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .context import (
    ToolDeps,
    TurnContext,
    compact,
    parse_date,
    parse_when,
    parse_zone,
    resolve_field,
    resolve_zone,
    tool,
)

_NO_ZONE = {"ninguna", "ninguno", "sin zona", "none"}


SNAPSHOT_PARTS = ("zones", "lots", "recent_log", "tasks", "reminders", "analysis")


def farm_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_fields() -> dict:
        """List the account's fields (plots / garden beds) with their active lots and last activity."""
        overview = await deps.farm.overview(ctx.actor)
        return {"fields": compact(overview)}

    @tool
    async def get_farm_snapshot(
        field: Optional[str] = None, include: Optional[list[str]] = None, season: Optional[str] = None
    ) -> dict:
        """A field's current state in ONE call — start here before reading zones, lots, the bitácora or tasks one by
        one. include (default all): zones (each with its active lots, pH and last bitácora entry), lots (every lot
        by status), recent_log, tasks (next open ones), reminders (today's), analysis (the last completed one).
        season: only that season's lots ("26/27")."""
        target = await resolve_field(deps, ctx, field)
        snap = await deps.snapshot.snapshot(ctx.actor, target.id, season)
        wanted = set(include or SNAPSHOT_PARTS)
        parts = {
            "zones": {"zones": snap.zones, "unzoned_lots": snap.unzoned_lots},
            "lots": {"lots_by_status": snap.lots_by_status},
            "recent_log": {"recent_log": snap.recent_log},
            "tasks": {"next_tasks": snap.next_tasks, "open_tasks": snap.open_tasks},
            "reminders": {"reminders_today": snap.reminders_today},
            "analysis": {"last_analysis": snap.last_analysis},
        }
        result: dict = {"field_name": snap.field_name, "ph": snap.ph}
        for name in SNAPSHOT_PARTS:
            if name in wanted:
                result.update(parts[name])
        return compact(result)

    @tool
    async def list_lots(
        field: Optional[str] = None, status: Optional[str] = None, zone: Optional[str] = None
    ) -> dict:
        """List lots (crop batches). field: field name or id (optional).
        status: planned|seedbed|planted|growing|harvesting|harvested|failed.
        zone: e.g. 'cantero 3' (requires the field, or the conversation's field)."""
        target = await resolve_field(deps, ctx, field) if field or zone else None
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        cycles = await deps.farm.list_lots(
            ctx.actor, field_id=target.id if target else None, status=status, zone_id=zone_id
        )
        return {"lots": compact(cycles)}

    @tool
    async def list_zones(field: Optional[str] = None) -> dict:
        """List the zones of a field: its numbered cajones, canteros, invernaderos and sistemas de hidroponía.
        Crops, events and the daily tracking photos are organized by zone."""
        target = await resolve_field(deps, ctx, field)
        zones = await deps.farm.list_zones(ctx.actor, target.id)
        return {"field_name": target.name, "zones": compact(zones)}

    @tool
    async def list_recent_events(
        field: Optional[str] = None, event_type: Optional[str] = None, days: int = 14, limit: int = 30,
        zone: Optional[str] = None,
    ) -> dict:
        """List registered field events (irrigation, sowing, treatments, sightings, harvests...)
        from the last `days` days. zone: only that zone's, e.g. 'cantero 3' (needs the field)."""
        target = await resolve_field(deps, ctx, field) if (field or zone) else None
        field_id = target.id if target else None
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        events = await deps.farm.list_events(
            ctx.actor,
            field_id=field_id,
            zone_id=zone_id,
            event_type=event_type,
            since=utcnow() - timedelta(days=max(1, min(days, 365))),
            limit=limit,
        )
        return {"events": compact(events)}

    @tool
    async def find_crop_in_catalog(name: str, variety: Optional[str] = None) -> dict:
        """Search the crop catalog (global + this account) by crop name, e.g. 'tomate', optional variety 'cherry'."""
        matches = await deps.farm.find_crop_masters(ctx.actor, name, variety)
        if not matches:
            matches = await deps.farm.list_crop_masters(ctx.actor, query=name, limit=10)
        return {"crops": compact(matches)}

    @tool
    async def get_field_sun_exposure(field: Optional[str] = None) -> dict:
        """Direct-sun hours for a field in summer/winter/equinox, computed from real solar astronomy and the
        field's plan (walls, trees, buildings with real shapes and heights) — not a guess. Two views: `by_season`
        (hours per compass octant N/NE/E/SE/S/SO/O/NO, an approximation) and, when the plan has an area and
        shade-casting elements, `environment` (the surroundings seen in the photos) and `plot` (the field's own
        growing plot, when drawn), each per season: mean hours of direct sun over a 1 m grid, the percent of the
        area in full sun (6+ h), part shade (3-6 h) and shade (<3 h), and where the sunniest and shadiest zones
        are. Use it to reason about what to plant where (sun-loving crops in the sunniest zone, shade-tolerant
        ones in the shadiest)."""
        target = await resolve_field(deps, ctx, field)
        result = await deps.farm.sun_exposure(ctx.actor, target.id)
        return compact(result)

    @tool
    async def get_field_soil_context(field: Optional[str] = None) -> dict:
        """Soil read for this field's location: in Argentina INTA's national datasets ("Suelos de la República
        Argentina" 1:500.000 + pH raster) — soil order/subgroup, texture, drainage, depth, alkalinity, erosion,
        floodability, topsoil pH — and, where the SoilGrids tiles are loaded (Argentina, Mexico), the ISRIC
        SoilGrids estimate by depth (0-30 cm): pH, organic carbon
        (g/kg), nitrogen (g/kg) and cation-exchange capacity (cmol(c)/kg). Regional estimates from models and maps
        (km to 250 m), not a lab analysis of this field and not per-plant precision. Cross-reference against a
        photo-based read (save_soil_sample) when both are available. None if the field has no coordinates."""
        target = await resolve_field(deps, ctx, field)
        target = await deps.farm.ensure_soilgrids(ctx.actor, target.id)  # local tiles, cached in the field
        return {"soil_context": compact(target.soil_context) if target.soil_context else None}

    @tool
    async def get_harvest_totals(field: Optional[str] = None, year: Optional[int] = None) -> dict:
        """Total harvested quantity (by unit) for a field in a given year (default: current year), summed
        from registered harvest events. Answers "how much did we harvest this year"."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        return compact(await deps.farm.harvest_totals(ctx.actor, field_id=field_id, year=year))

    @tool
    async def get_harvest_verdict(field: Optional[str] = None, lot_id: Optional[str] = None) -> dict:
        """Is it ready to harvest? With a photo in this message, does a quick dedicated visual check (not
        persisted as a report). Without one, falls back to the harvest_ready/harvest_verdict already in the
        latest periodic report of this field/cycle."""
        target = await resolve_field(deps, ctx, field)
        result = await deps.diagnosis.harvest_verdict(
            ctx.actor, target.id, UUID(lot_id) if lot_id else None, ctx.image_identifier
        )
        return compact(result)

    @tool
    async def log_events(entries: list[dict], field: Optional[str] = None) -> dict:
        """Register in the bitácora what was done, seen or deliberately NOT done, several entries in ONE call
        ("regué los canteros 1, 2 y 3 y fertilicé el 2 con 50 ml de té de compost"). Each entry:
        {type, zone?, zones?, lots?, occurred_at?, quantity?, unit?, notes?, outcome?, reason?, attach_current_photo?,
        followup_id?}
        - type: irrigation|fertilization|pest_control|sowing|transplant|harvest|inspection|observation|soil_prep|
          amendment|pruning|weeding|photo. inspection = a check-up (pest or disease seen, growth, state).
          Losses go through record_lot_loss; rain is logged by the system from the weather data.
        - outcome 'skipped' + reason: something the person decided NOT to do, and why ("no regué: llovió anoche").
          Only when THEY said so: never log a skipped entry from your own assumption — ask instead.
        - zone ('cantero 3') or zones (['cantero 1', 'cantero 2']: one entry per zone): it reaches every lot
          growing there. lots: lot ids, when it was only some lots. Neither: the whole field.
        - Products and doses as free text in notes ("Caldo bordelés 20 g/l"), with quantity + unit when there is
          an amount (10 'litros', 2 'kg'). occurred_at: ISO date/time (default now).
        - attach_current_photo: link the photo sent in this message.
        - followup_id: the problem being followed it is about (list_followups): it joins that follow-up's history."""
        target = await resolve_field(deps, ctx, field)
        created = []
        for entry in entries:
            if entry.get("attach_current_photo") and not ctx.image_identifier:
                raise InvalidInputError("There is no photo in this message to attach.")
            zones = [*([entry["zone"]] if entry.get("zone") else []), *(entry.get("zones") or [])]
            zone_ids = [(await resolve_zone(deps, ctx, target, z)).id for z in zones] or [None]
            for zone_id in zone_ids:
                event = await deps.farm.create_event(
                    ctx.actor,
                    FieldEventCreate(
                        field_id=target.id,
                        zone_id=zone_id,
                        lot_ids=[UUID(str(lot)) for lot in entry.get("lots") or []],
                        type=entry["type"],
                        occurred_at=parse_when(entry.get("occurred_at"), ctx.tz),
                        quantity=entry.get("quantity"),
                        unit=entry.get("unit"),
                        notes=entry.get("notes"),
                        image_identifier=ctx.image_identifier if entry.get("attach_current_photo") else None,
                        outcome=entry.get("outcome") or "done",
                        reason=entry.get("reason"),
                        followup_id=UUID(str(entry["followup_id"])) if entry.get("followup_id") else None,
                    ),
                )
                created.append({
                    "id": str(event.id), "type": event.type, "zone_id": event.zone_id and str(event.zone_id),
                    "lots_reached": len(event.lot_ids),
                    **({"outcome": "skipped"} if event.outcome == "skipped" else {}),
                })
        return {"logged": created, "field_name": target.name}

    @tool
    async def get_log(
        field: Optional[str] = None, zone: Optional[str] = None, lot_id: Optional[str] = None, days: int = 30,
        event_type: Optional[str] = None, limit: int = 60,
    ) -> dict:
        """Read the bitácora by day: of a lot (lot_id: everything that reached it, also what was logged on its
        zone or the whole field, and the analyses that covered it), of a zone ('cantero 3') or of the field.
        Use it to answer "¿qué se le aplicó a este lote?", "¿cuándo regué el cantero 2?". event_type filters."""
        target = await resolve_field(deps, ctx, field) if (field or zone or not lot_id) else None
        scope: dict = {}
        if lot_id:
            scope["lot_id"] = UUID(lot_id)
        elif zone:
            scope["zone_id"] = (await resolve_zone(deps, ctx, target, zone)).id
        else:
            scope["field_id"] = target.id
        page = await deps.log.log(
            ctx.actor, since=utcnow() - timedelta(days=max(1, min(days, 730))), limit=limit, event_type=event_type,
            **scope,
        )
        return {"days": compact(page.days), "more": page.next_before is not None}

    @tool
    async def record_lot_loss(
        lot_id: str, quantity: Optional[float] = None, percent: Optional[float] = None, cause: Optional[str] = None,
        notes: Optional[str] = None, occurred_at: Optional[str] = None,
    ) -> dict:
        """Log plants or seeds LOST in one lot ("se perdieron 30 plantines", "no germinó la mitad"): quantity in the
        lot's unit or percent of what is alive. The lot keeps its sown quantity; its live quantity drops, and it
        fails only when nothing is left. cause: no_germination|pest|disease|frost|heat|waterlogging|drought|animals|
        other. If they resowed, use resow_lot instead (it logs the loss too)."""
        lot = await deps.farm.get_lot(ctx.actor, UUID(lot_id))
        event = await deps.farm.create_event(ctx.actor, FieldEventCreate(
            field_id=lot.field_id, lot_ids=[lot.id], type="loss", quantity=quantity,
            occurred_at=parse_when(occurred_at, ctx.tz), reason=notes,
            data={k: v for k, v in {"percent": percent, "cause": cause}.items() if v is not None},
        ))
        after = await deps.farm.get_lot(ctx.actor, lot.id)
        return {
            "lost": event.quantity, "unit": event.unit, "lot": after.label,
            "sown": after.quantity, "alive": after.alive_quantity, "status": after.status,
        }

    @tool
    async def count_lot_plants(lot_id: str, count: Optional[float] = None, notes: Optional[str] = None) -> dict:
        """Count what is alive in a lot. With `count`: the person's own count (or one they confirmed), saved; it
        resets the live quantity. Without it and with a photo in this message: counts the plants in the photo and
        returns a PROPOSAL — nothing is saved. Tell them the count and range, compare with what should be alive,
        and ask before saving it (call again with count=...), or before logging the difference as a loss."""
        lot = await deps.farm.get_lot(ctx.actor, UUID(lot_id))
        if count is None:
            if not ctx.image_identifier:
                raise InvalidInputError("No count given and no photo in this message: ask for one or the other.")
            crop = await deps.farm.get_crop_master(ctx.actor, lot.crop_master_id)
            result = await deps.diagnosis.count_plants(
                ctx.actor, ctx.image_identifier, crop_name=crop.name, expected=lot.alive_quantity
            )
            return {
                "proposal": compact(result), "lot": lot.label, "expected_alive": lot.alive_quantity,
                "saved": False,
            }
        await deps.farm.create_event(ctx.actor, FieldEventCreate(
            field_id=lot.field_id, lot_ids=[lot.id], type="inspection", notes=notes, data={"count": count},
            image_identifier=ctx.image_identifier,
        ))
        after = await deps.farm.get_lot(ctx.actor, lot.id)
        return {"saved": True, "lot": after.label, "alive": after.alive_quantity, "sown": after.quantity}

    return [
        list_fields,
        get_farm_snapshot,
        list_lots,
        list_zones,
        list_recent_events,
        find_crop_in_catalog,
        get_field_sun_exposure,
        get_field_soil_context,
        get_harvest_totals,
        get_harvest_verdict,
        get_log,
        log_events,
        record_lot_loss,
        count_lot_plants,
    ]


def farm_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    """Write tools only exposed to owner / tecnico."""

    @tool
    async def create_field(
        name: str,
        city: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        area_m2: Optional[float] = None,
        soil_type: Optional[str] = None,
        description: Optional[str] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        layout_objects: Optional[list[dict]] = None,
    ) -> dict:
        """Create a field (plot, garden bed, greenhouse...). Coordinates enable weather forecasts and alerts.
        length_m/width_m: typed dimensions. layout_objects: the plan of things around the plot that cast
        shade, in meters from the field center (x East+, y North+), each {id, type: pared|cerco|arbol|
        estructura|pileta|cantero|entorno|campo|otro, label, height_m, source: manual, kind: polygon|polyline|
        circle} plus its geometry: points [[x, y], ...] for polygon/polyline (polyline also thickness_m), or
        x_m/y_m/radius_m for a circle. Users normally draw this in the web app or build it from a photo; only
        fill it here if the user states positions explicitly."""
        created = await deps.farm.create_field(
            ctx.actor,
            FieldCreate(
                name=name,
                city=city,
                latitude=latitude,
                longitude=longitude,
                area_m2=area_m2,
                soil_type=soil_type,
                description=description,
                length_m=length_m,
                width_m=width_m,
                layout_objects=[LayoutObject(**o) for o in (layout_objects or [])],
            ),
        )
        if created.latitude is not None:
            try:
                await deps.satellite.check_field(ctx.actor, created.id)
            except Exception:
                pass  # best-effort context; a field is still successfully created without it
        return {"created_field": compact(created)}

    @tool
    async def update_field(
        field: str,
        name: Optional[str] = None,
        city: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        area_m2: Optional[float] = None,
        soil_type: Optional[str] = None,
        description: Optional[str] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        layout_objects: Optional[list[dict]] = None,
    ) -> dict:
        """Update a field's data (any subset of fields). layout_objects (same shape as in create_field), if
        given, REPLACES the full list — pass the complete set including any you want to keep, not just the
        new one."""
        target = await resolve_field(deps, ctx, field)
        values = {
            "name": name,
            "city": city,
            "latitude": latitude,
            "longitude": longitude,
            "area_m2": area_m2,
            "soil_type": soil_type,
            "description": description,
            "length_m": length_m,
            "width_m": width_m,
            "layout_objects": [LayoutObject(**o) for o in layout_objects] if layout_objects is not None else None,
        }
        update = FieldUpdate(**{k: v for k, v in values.items() if v is not None})
        updated = await deps.farm.update_field(ctx.actor, target.id, update)
        return {"updated_field": compact(updated)}

    @tool
    async def add_crop_to_catalog(
        name: str,
        variety: Optional[str] = None,
        scientific_name: Optional[str] = None,
        family: Optional[str] = None,
        growth_period_days: Optional[int] = None,
        planting_season: Optional[str] = None,
        harvest_season: Optional[str] = None,
        names_by_locale: Optional[dict[str, str]] = None,
    ) -> dict:
        """Add a crop/variety to this account's catalog when find_crop_in_catalog has no suitable entry.
        names_by_locale: what it is called elsewhere, e.g. {"es-MX": "jitomate"}, so it is found by either name."""
        crop = await deps.farm.create_crop_master(
            ctx.actor,
            CropMasterCreate(
                name=name,
                variety=variety,
                scientific_name=scientific_name,
                family=family,
                growth_period_days=growth_period_days,
                planting_season=planting_season,
                harvest_season=harvest_season,
                i18n=names_by_locale or {},
            ),
        )
        return {"created_crop": compact(crop)}

    @tool
    async def create_lot(
        crop_name: str,
        field: Optional[str] = None,
        variety: Optional[str] = None,
        status: str = "planted",
        planting_date: Optional[str] = None,
        expected_harvest_date: Optional[str] = None,
        notes: Optional[str] = None,
        zone: Optional[str] = None,
        zones: Optional[list[str]] = None,
        season: Optional[str] = None,
        number: Optional[int] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        expected_yield_kg: Optional[float] = None,
        expected_price: Optional[float] = None,
    ) -> dict:
        """Start a lot (lote: one batch of a crop sown together). Resolves the crop from the catalog by name,
        adding it to the account catalog if missing. status: planned|seedbed|planted|growing. Dates YYYY-MM-DD.
        If expected_harvest_date is omitted it is estimated from the crop's growth period.
        zone: the zone it grows in, e.g. 'cantero 3'; zones: several, when the same batch went into more than one.
        season ("26/27") and number (2 = second sowing of that zone this season): the user's own labels.
        quantity + unit (plantas | semillas | gramos), expected_yield_kg, expected_price (per kg): optional, they
        feed the cost per plant and the break-even in get_budget_summary."""
        target = await resolve_field(deps, ctx, field)
        zone_ids = [(await resolve_zone(deps, ctx, target, z)).id for z in [*([zone] if zone else []), *(zones or [])]]
        matches = await deps.farm.find_crop_masters(ctx.actor, crop_name, variety)
        added = False
        if matches:
            crop = matches[0]
        else:
            crop = await deps.farm.create_crop_master(ctx.actor, CropMasterCreate(name=crop_name, variety=variety))
            added = True
        planted = parse_date(planting_date)
        if planted is None and status in ("planted", "growing"):
            planted = utcnow().astimezone(ctx.tz).date()
        expected = parse_date(expected_harvest_date)
        if expected is None and planted and crop.growth_period_days:
            expected = planted + timedelta(days=crop.growth_period_days)
        cycle = await deps.farm.create_lot(
            ctx.actor,
            LotCreate(
                field_id=target.id,
                crop_master_id=crop.id,
                zone_ids=zone_ids,
                season=season,
                number=number,
                status=status,
                planting_date=planted,
                expected_harvest_date=expected,
                notes=notes,
                quantity=quantity,
                unit=unit or ("plantas" if quantity else None),
                expected_yield_kg=expected_yield_kg,
                expected_price=expected_price,
            ),
        )
        return {
            "created_lot": compact(cycle),
            "field_name": target.name,
            "crop": compact(crop),
            "crop_added_to_catalog": added,
        }

    @tool
    async def update_lot(
        lot_id: str,
        status: Optional[str] = None,
        actual_harvest_date: Optional[str] = None,
        expected_harvest_date: Optional[str] = None,
        notes: Optional[str] = None,
        zone: Optional[str] = None,
        season: Optional[str] = None,
        number: Optional[int] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
    ) -> dict:
        """Update a lot: status (planned|seedbed|planted|growing|harvesting|harvested|failed), harvest dates
        (YYYY-MM-DD), notes, season ("26/27"), number, zone (move it to e.g. 'cantero 2'; 'ninguna' takes it out
        of its zones). quantity + unit: ONLY to fix what was sown when it was typed wrong — plants lost go through
        record_lot_loss, a resowing through resow_lot, a fresh count through count_lot_plants."""
        values = {
            "quantity": quantity,
            "unit": unit,
            "status": status,
            "actual_harvest_date": parse_date(actual_harvest_date),
            "expected_harvest_date": parse_date(expected_harvest_date),
            "notes": notes,
            "season": season,
            "number": number,
        }
        values = {k: v for k, v in values.items() if v is not None}
        if zone is not None:
            if zone.strip().lower() in _NO_ZONE:
                values["zone_ids"] = []
            else:
                current = await deps.farm.get_lot(ctx.actor, UUID(lot_id))
                field_read = await deps.farm.get_field(ctx.actor, current.field_id)
                values["zone_ids"] = [(await resolve_zone(deps, ctx, field_read, zone)).id]
        update = LotUpdate(**values)
        cycle = await deps.farm.update_lot(ctx.actor, UUID(lot_id), update)
        return {"updated_lot": compact(cycle)}

    @tool
    async def resow_lot(
        lot_id: str,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        planting_date: Optional[str] = None,
        zone: Optional[str] = None,
        lost_quantity: Optional[float] = None,
        lost_percent: Optional[float] = None,
        cause: Optional[str] = None,
        notes: Optional[str] = None,
        seed_lot_id: Optional[str] = None,
    ) -> dict:
        """Resow (part of) a lot ("no germinaron 40 de las 120, resembramos 40"): logs the loss on the original if
        given (lost_quantity or lost_percent, cause as in record_lot_loss) and starts a NEW lot that replaces it,
        same crop and zones unless zone says otherwise, with its sowing in the bitácora. The original lot stays with
        what is left of it (it fails only if nothing is). seed_lot_id: take `quantity` seeds from that inventory lot
        (list_seed_inventory)."""
        original = await deps.farm.get_lot(ctx.actor, UUID(lot_id))
        zone_ids = None
        if zone:
            field_read = await deps.farm.get_field(ctx.actor, original.field_id)
            zone_ids = [(await resolve_zone(deps, ctx, field_read, zone)).id]
        before, new = await deps.farm.resow(
            ctx.actor, original.id, quantity=quantity, unit=unit, planting_date=parse_date(planting_date),
            zone_ids=zone_ids, lost_quantity=lost_quantity, lost_percent=lost_percent, cause=cause, notes=notes,
        )
        result = {
            "original": {"lot": before.label, "sown": before.quantity, "alive": before.alive_quantity,
                         "status": before.status},
            "resown_lot": compact(new),
        }
        if seed_lot_id and quantity:
            try:
                await deps.inventory.consume_seed_lot(ctx.actor, UUID(seed_lot_id), quantity, new.unit)
                result["seed_consumed"] = quantity
            except Exception as e:  # noqa: BLE001 - the resowing is already logged; say what failed
                result["seed_not_consumed"] = getattr(e, "message", str(e))
        return result

    @tool
    async def create_zone(
        zone: str, field: Optional[str] = None, name: Optional[str] = None, notes: Optional[str] = None
    ) -> dict:
        """Create a zone in a field: a numbered cajón, cantero, invernadero or hidroponía, e.g. zone='cantero 3'
        or just 'invernadero' (takes the next free number). name: optional nickname. Afterwards assign crops to it
        with create_lot / update_lot (zone=...)."""
        target = await resolve_field(deps, ctx, field)
        zone_type, number = parse_zone(zone)
        if zone_type is None:
            raise InvalidInputError("Say which kind of zone: cajón, cantero, invernadero or hidroponía.")
        created = await deps.farm.create_zone(
            ctx.actor, target.id, FieldZoneCreate(type=zone_type, number=number, name=name, notes=notes)
        )
        return {"created_zone": compact(created), "field_name": target.name}

    @tool
    async def delete_field(field: str) -> dict:
        """Soft-delete a field: it disappears from lists and reports, but the data is kept and can be
        restored by support if needed — it is not permanent. Even so, ONLY call this after the user has
        explicitly confirmed in a message of their own: first restate which field you're about to remove
        and what that implies (its lots and events stop showing up), then wait for an explicit yes.
        Never call this in the same turn as the first request to delete something."""
        target = await resolve_field(deps, ctx, field)
        await deps.farm.delete_field(ctx.actor, target.id)
        return {"deleted_field": target.name}

    @tool
    async def delete_lot(lot_id: str) -> dict:
        """Soft-delete a lot (recoverable, not permanent). Same rule as delete_field: restate what
        you're about to remove and wait for the user's explicit confirmation in a separate message first.
        Use list_lots to find the id if you don't have it."""
        await deps.farm.delete_lot(ctx.actor, UUID(lot_id))
        return {"deleted_lot_id": lot_id}

    return [
        create_field,
        update_field,
        add_crop_to_catalog,
        create_zone,
        create_lot,
        update_lot,
        resow_lot,
        delete_field,
        delete_lot,
    ]
