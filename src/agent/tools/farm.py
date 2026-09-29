from datetime import timedelta
from typing import Optional
from uuid import UUID

from src.application.farm.schemas import (
    CropCycleCreate,
    CropCycleUpdate,
    CropMasterCreate,
    FieldCreate,
    FieldEventCreate,
    FieldUpdate,
    Obstacle,
)
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, parse_date, parse_when, resolve_field, tool


def farm_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_fields() -> dict:
        """List the account's fields (plots / garden beds) with their active crop cycles and last activity."""
        overview = await deps.farm.overview(ctx.actor)
        return {"fields": compact(overview)}

    @tool
    async def list_crop_cycles(field: Optional[str] = None, status: Optional[str] = None) -> dict:
        """List crop cycles. field: field name or id (optional). status: planned|planted|growing|harvested|failed."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        cycles = await deps.farm.list_crop_cycles(ctx.actor, field_id=field_id, status=status)
        return {"crop_cycles": compact(cycles)}

    @tool
    async def list_recent_events(
        field: Optional[str] = None, event_type: Optional[str] = None, days: int = 14, limit: int = 30
    ) -> dict:
        """List registered field events (irrigation, sowing, treatments, sightings, harvests...)
        from the last `days` days."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        events = await deps.farm.list_events(
            ctx.actor,
            field_id=field_id,
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
        """Direct-sun hours per compass octant (N/NE/E/SE/S/SO/O/NO) for a field, in summer/winter/equinox,
        computed from real solar astronomy and declared obstacles — not a guess. Use this to reason about
        what to plant where (sun-loving crops toward the octants with the most hours, shade-tolerant ones
        toward the least)."""
        target = await resolve_field(deps, ctx, field)
        result = await deps.farm.sun_exposure(ctx.actor, target.id)
        return compact(result)

    @tool
    async def get_harvest_totals(field: Optional[str] = None, year: Optional[int] = None) -> dict:
        """Total harvested quantity (by unit) for a field in a given year (default: current year), summed
        from registered harvest events. Answers "how much did we harvest this year"."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        return compact(await deps.farm.harvest_totals(ctx.actor, field_id=field_id, year=year))

    @tool
    async def get_harvest_verdict(field: Optional[str] = None, crop_cycle_id: Optional[str] = None) -> dict:
        """Is it ready to harvest? With a photo in this message, does a quick dedicated visual check (not
        persisted as a report). Without one, falls back to the harvest_ready/harvest_verdict already in the
        latest periodic report of this field/cycle."""
        target = await resolve_field(deps, ctx, field)
        result = await deps.diagnosis.harvest_verdict(
            ctx.actor, target.id, UUID(crop_cycle_id) if crop_cycle_id else None, ctx.image_identifier
        )
        return compact(result)

    @tool
    async def log_event(
        event_type: str,
        field: Optional[str] = None,
        occurred_at: Optional[str] = None,
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        notes: Optional[str] = None,
        crop_cycle_id: Optional[str] = None,
        attach_current_photo: bool = False,
    ) -> dict:
        """Register something that happened in a field.
        event_type: sowing|transplant|irrigation|fertilization|treatment|pruning|weeding|pest_sighting|
        disease_sighting|harvest|observation|photo. occurred_at: ISO date/time (default now).
        quantity+unit e.g. 10 'litros', 2 'kg'. attach_current_photo: link the photo sent in this message."""
        target = await resolve_field(deps, ctx, field)
        if attach_current_photo and not ctx.image_identifier:
            raise InvalidInputError("There is no photo in this message to attach.")
        event = await deps.farm.create_event(
            ctx.actor,
            FieldEventCreate(
                field_id=target.id,
                crop_cycle_id=crop_cycle_id or None,
                type=event_type,
                occurred_at=parse_when(occurred_at, ctx.tz),
                quantity=quantity,
                unit=unit,
                notes=notes,
                image_identifier=ctx.image_identifier if attach_current_photo else None,
            ),
        )
        return {"created_event": compact(event), "field_name": target.name}

    return [
        list_fields,
        list_crop_cycles,
        list_recent_events,
        find_crop_in_catalog,
        get_field_sun_exposure,
        get_harvest_totals,
        get_harvest_verdict,
        log_event,
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
        orientation_degrees: Optional[float] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        obstacles: Optional[list[dict]] = None,
    ) -> dict:
        """Create a field (plot, garden bed, greenhouse...). Coordinates enable weather forecasts and alerts.
        orientation_degrees: compass bearing the long side faces (0-360, 0=N). length_m/width_m: typed
        dimensions. obstacles: list of {type: pared|arbol|estructura, height_m, direction: N|NE|E|SE|S|SO|O|NO}
        — declaring these enables get_field_sun_exposure (real sol/sombra, not a guess)."""
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
                orientation_degrees=orientation_degrees,
                length_m=length_m,
                width_m=width_m,
                obstacles=[Obstacle(**o) for o in (obstacles or [])],
            ),
        )
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
        orientation_degrees: Optional[float] = None,
        length_m: Optional[float] = None,
        width_m: Optional[float] = None,
        obstacles: Optional[list[dict]] = None,
    ) -> dict:
        """Update a field's data (any subset of fields). obstacles, if given, REPLACES the full list — pass
        the complete set including any you want to keep, not just the new one."""
        target = await resolve_field(deps, ctx, field)
        values = {
            "name": name,
            "city": city,
            "latitude": latitude,
            "longitude": longitude,
            "area_m2": area_m2,
            "soil_type": soil_type,
            "description": description,
            "orientation_degrees": orientation_degrees,
            "length_m": length_m,
            "width_m": width_m,
            "obstacles": [Obstacle(**o) for o in obstacles] if obstacles is not None else None,
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
    ) -> dict:
        """Add a crop/variety to this account's catalog when find_crop_in_catalog has no suitable entry."""
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
            ),
        )
        return {"created_crop": compact(crop)}

    @tool
    async def create_crop_cycle(
        crop_name: str,
        field: Optional[str] = None,
        variety: Optional[str] = None,
        status: str = "planted",
        planting_date: Optional[str] = None,
        expected_harvest_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Start a crop cycle (a crop planted/planned in a field). Resolves the crop from the catalog by name,
        adding it to the account catalog if missing. status: planned|planted|growing. Dates YYYY-MM-DD.
        If expected_harvest_date is omitted it is estimated from the crop's growth period."""
        target = await resolve_field(deps, ctx, field)
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
        cycle = await deps.farm.create_crop_cycle(
            ctx.actor,
            CropCycleCreate(
                field_id=target.id,
                crop_master_id=crop.id,
                status=status,
                planting_date=planted,
                expected_harvest_date=expected,
                notes=notes,
            ),
        )
        return {
            "created_crop_cycle": compact(cycle),
            "field_name": target.name,
            "crop": compact(crop),
            "crop_added_to_catalog": added,
        }

    @tool
    async def update_crop_cycle(
        crop_cycle_id: str,
        status: Optional[str] = None,
        actual_harvest_date: Optional[str] = None,
        expected_harvest_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Update a crop cycle: status (planned|planted|growing|harvested|failed), harvest dates (YYYY-MM-DD), notes."""
        values = {
            "status": status,
            "actual_harvest_date": parse_date(actual_harvest_date),
            "expected_harvest_date": parse_date(expected_harvest_date),
            "notes": notes,
        }
        update = CropCycleUpdate(**{k: v for k, v in values.items() if v is not None})
        cycle = await deps.farm.update_crop_cycle(ctx.actor, UUID(crop_cycle_id), update)
        return {"updated_crop_cycle": compact(cycle)}

    @tool
    async def delete_field(field: str) -> dict:
        """Soft-delete a field: it disappears from lists and reports, but the data is kept and can be
        restored by support if needed — it is not permanent. Even so, ONLY call this after the user has
        explicitly confirmed in a message of their own: first restate which field you're about to remove
        and what that implies (its crop cycles and events stop showing up), then wait for an explicit yes.
        Never call this in the same turn as the first request to delete something."""
        target = await resolve_field(deps, ctx, field)
        await deps.farm.delete_field(ctx.actor, target.id)
        return {"deleted_field": target.name}

    @tool
    async def delete_crop_cycle(crop_cycle_id: str) -> dict:
        """Soft-delete a crop cycle (recoverable, not permanent). Same rule as delete_field: restate what
        you're about to remove and wait for the user's explicit confirmation in a separate message first.
        Use list_crop_cycles to find the id if you don't have it."""
        await deps.farm.delete_crop_cycle(ctx.actor, UUID(crop_cycle_id))
        return {"deleted_crop_cycle_id": crop_cycle_id}

    return [
        create_field,
        update_field,
        add_crop_to_catalog,
        create_crop_cycle,
        update_crop_cycle,
        delete_field,
        delete_crop_cycle,
    ]
