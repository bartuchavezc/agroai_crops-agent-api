"""Planning tools: reminders and crop plans — the same data the web's Planificación tab edits.

Reminders are notified in-app when due (a batch job). A lot's stage plan (germinación, traspaso,
etapas clave, posible cosecha) comes from its crop's template; a general plan has objectives, zones, stages and
crops (once, staggered or perennial) whose sowings become planned lots with their "Sembrar" tasks."""
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from src.application.planning.schemas import (
    PlanCreate,
    PlanUpdate,
    ReminderCreate,
    ReminderUpdate,
    LotSown,
    PlanCropCreate,
    StageCreate,
)
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, parse_date, resolve_field, resolve_zone, tool
from .management import _Resolvers


def _when(value: str, ctx: TurnContext, deps: ToolDeps) -> datetime:
    """YYYY-MM-DD (-> 09:00 local) or YYYY-MM-DDTHH:MM (local unless it carries an offset)."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidInputError(f"Invalid date/time '{value}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.") from None
    if len(value.strip()) <= 10:
        return deps.planning.at_local(parsed.date())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ctx.tz)


async def _crop_id(deps: ToolDeps, ctx: TurnContext, crop: str) -> UUID:
    try:
        return (await deps.farm.get_crop_master(ctx.actor, UUID(crop))).id
    except ValueError:
        pass
    name, _, variety = crop.partition(" ")
    matches = await deps.farm.find_crop_masters(ctx.actor, crop) or await deps.farm.find_crop_masters(
        ctx.actor, name, variety or None
    )
    if not matches:
        raise InvalidInputError(f"'{crop}' is not in the catalog. Use find_crop_in_catalog / add_crop_to_catalog.")
    return matches[0].id


async def _where(deps: ToolDeps, ctx: TurnContext, field: Optional[str], zone: Optional[str]) -> dict:
    """field/zone arguments -> ids (zone implies its field)."""
    if not field and not zone:
        return {}
    target = await resolve_field(deps, ctx, field)
    values = {"field_id": target.id}
    if zone:
        values["zone_id"] = (await resolve_zone(deps, ctx, target, zone)).id
    return values


def planning_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    refs = _Resolvers(deps, ctx)

    @tool
    async def list_reminders(
        days_ahead: int = 14, include_inactive: bool = False, field: Optional[str] = None, zone: Optional[str] = None
    ) -> dict:
        """Active reminders whose next notice falls within `days_ahead` days. A reminder only notifies ("regar el
        cantero 2", "si llueve no regar"); it is never done. include_inactive also lists paused and finished ones.
        zone: only that zone's, e.g. 'cantero 3'."""
        target = await resolve_field(deps, ctx, field) if (field or zone) else None
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        until = utcnow() + timedelta(days=max(1, min(days_ahead, 366)))
        items = await deps.planning.list_reminders(
            ctx.actor, status=None if include_inactive else "activo", until=until,
            field_id=target.id if target else None, zone_id=zone_id,
        )
        return {"now": utcnow().astimezone(ctx.tz).isoformat(), "reminders": compact(items)}

    @tool
    async def add_reminder(
        title: str,
        when: str,
        description: Optional[str] = None,
        field: Optional[str] = None,
        zone: Optional[str] = None,
        lot_id: Optional[str] = None,
        recurrence: str = "none",
        every_days: Optional[int] = None,
        until: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> dict:
        """Schedule a reminder: a notice that arrives as an in-app notification at `when` (YYYY-MM-DD = 09:00, or
        YYYY-MM-DDTHH:MM local) — "regar", "revisar el pulgón". recurrence: none|daily|weekly|every_n_days (with
        every_days), optionally until YYYY-MM-DD. assignee: member name/email or "yo" (default: everyone in the
        account). Work to track with a state and someone in charge is a task (add_tasks), not a reminder."""
        reminder = await deps.planning.create_reminder(
            ctx.actor,
            ReminderCreate(
                title=title,
                due_at=_when(when, ctx, deps),
                description=description,
                recurrence=recurrence,
                interval_days=every_days,
                until=parse_date(until),
                assigned_to=await refs.member_value(assignee),
                lot_id=UUID(lot_id) if lot_id else None,
                **await _where(deps, ctx, field, zone),
            ),
        )
        return {"created_reminder": compact(reminder)}

    @tool
    async def update_reminder(
        reminder_id: str, when: Optional[str] = None, status: Optional[str] = None, title: Optional[str] = None,
        recurrence: Optional[str] = None, every_days: Optional[int] = None, until: Optional[str] = None,
    ) -> dict:
        """Reschedule (when: YYYY-MM-DD = 09:00, or YYYY-MM-DDTHH:MM), pause/resume (status: pausado|activo) or
        change a reminder's text or recurrence. Only what you pass changes."""
        values: dict = {
            "due_at": _when(when, ctx, deps) if when else None, "status": status, "title": title,
            "recurrence": recurrence, "interval_days": every_days, "until": parse_date(until),
        }
        updated = await deps.planning.update_reminder(
            ctx.actor, UUID(reminder_id), ReminderUpdate(**{k: v for k, v in values.items() if v is not None})
        )
        return {"reminder": compact(updated)}

    @tool
    async def list_plans(field: Optional[str] = None, include_archived: bool = False) -> dict:
        """Crop plans of the account: per lot (kind ciclo) and long roadmaps (kind largo)."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        plans = await deps.planning.list_plans(ctx.actor, field_id=field_id)
        if not include_archived:
            plans = [p for p in plans if p.status != "archivado"]
        return {"plans": compact(plans)}

    @tool
    async def get_plan(plan_id: str) -> dict:
        """A plan with its objectives, zones, stages, crops, the lots it planned, its tasks and reminders."""
        return {"plan": compact(await deps.planning.get_plan(ctx.actor, UUID(plan_id)))}

    @tool
    async def preview_crop_stage_plan(lot_id: str) -> dict:
        """Proposed stages + reminders for a lot from its crop's typical timeline (germinación,
        traspaso, etapas clave, posible cosecha). Nothing is saved: show it and offer generate_crop_stage_plan."""
        return {"proposal": compact(await deps.planning.propose_cycle_plan(ctx.actor, UUID(lot_id)))}

    return [
        list_reminders,
        add_reminder,
        update_reminder,
        list_plans,
        get_plan,
        preview_crop_stage_plan,
    ]


def planning_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    """Plans, stages and plan crops: owner / tecnico."""

    @tool
    async def generate_crop_stage_plan(lot_id: str) -> dict:
        """Save a lot's stage plan and its reminders (germinación, traspaso, etapas clave, posible
        cosecha, cosecha estimada). Regenerating replaces what was generated before."""
        result = await deps.planning.apply_cycle_plan(ctx.actor, UUID(lot_id))
        return {"applied": compact(result)}

    async def _plan_crop(entry: dict, field: Optional[str]) -> PlanCropCreate:
        crop_id = await _crop_id(deps, ctx, entry["crop"])
        zones = [*([entry["zone"]] if entry.get("zone") else []), *(entry.get("zones") or [])]
        zone_ids = [(await _where(deps, ctx, field, z))["zone_id"] for z in zones]
        seed_lot_id, unit = None, entry.get("unit")
        if entry.get("use_seed_lot"):
            lots = await deps.inventory.list_seed_lots(ctx.actor, crop_master_id=crop_id)
            if not lots:
                raise InvalidInputError(f"There is no seed lot of {entry['crop']} in inventory.")
            seed_lot_id, unit = lots[0].id, unit or lots[0].unit
        return PlanCropCreate(
            crop_master_id=crop_id, mode=entry.get("mode", "single"), start_date=parse_date(entry["start_date"]),
            count=entry.get("count", 1), every_days=entry.get("every_days"), quantity=entry.get("quantity"),
            unit=unit, zone_ids=zone_ids, seed_lot_id=seed_lot_id, notes=entry.get("notes"),
        )

    @tool
    async def create_plan(
        name: str,
        objectives: Optional[str] = None,
        field: Optional[str] = None,
        zones: Optional[list[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        notes: Optional[str] = None,
        stages: Optional[list[dict]] = None,
        crops: Optional[list[dict]] = None,
    ) -> dict:
        """Create a general plan: the intent ("Plan Cantero 1: hoja y raíz fina", "Plan alimentación anual"), its
        objectives, the zones it covers ('cantero 1'...), and in ONE call its stages and crops.
        stages: [{name, stage: germinacion|plantin|traspaso|vegetativo|floracion|fructificacion|cosecha|
        establecimiento|poda|descanso|otro, start_date, end_date?, remind?: bool}].
        crops: [{crop, mode: single|staggered|perennial, start_date, count? and every_days? (staggered: e.g. lettuce
        6 times every 15 days), quantity? per sowing, unit?, zone?/zones? (default: the plan's), use_seed_lot?}] —
        every sowing becomes a planned lot with a "Sembrar" task on its date. Dates YYYY-MM-DD."""
        target = await resolve_field(deps, ctx, field)
        zone_ids = [(await resolve_zone(deps, ctx, target, z)).id for z in zones or []]
        plan = await deps.planning.create_plan(
            ctx.actor,
            PlanCreate(
                name=name,
                kind="largo",
                field_id=target.id,
                zone_ids=zone_ids,
                objectives=objectives,
                start_date=parse_date(start_date),
                end_date=parse_date(end_date),
                notes=notes,
                stages=[
                    StageCreate(
                        name=s["name"], stage=s.get("stage", "otro"), start_date=parse_date(s["start_date"]),
                        end_date=parse_date(s.get("end_date")), notes=s.get("notes"), remind=bool(s.get("remind")),
                    )
                    for s in (stages or [])
                ],
                crops=[await _plan_crop(c, target.name) for c in crops or []],
            ),
        )
        return {"created_plan": compact(plan)}

    @tool
    async def add_plan_crops(plan_id: str, crops: list[dict], field: Optional[str] = None) -> dict:
        """Add crops to a plan in ONE call; same shape as create_plan's crops. Each sowing becomes a planned lot with
        its "Sembrar" task."""
        created = [
            await deps.planning.add_plan_crop(ctx.actor, UUID(plan_id), await _plan_crop(c, field)) for c in crops
        ]
        return {"added_crops": compact(created)}

    @tool
    async def add_plan_stage(
        plan_id: str,
        name: str,
        start_date: str,
        end_date: Optional[str] = None,
        stage: str = "otro",
        notes: Optional[str] = None,
        remind: bool = True,
    ) -> dict:
        """Add a stage/period to a plan (e.g. "Poda invernal" 2027-07-01..07-31); remind=True schedules a
        reminder on its start date."""
        created = await deps.planning.add_stage(
            ctx.actor,
            UUID(plan_id),
            StageCreate(
                name=name, stage=stage, start_date=parse_date(start_date), end_date=parse_date(end_date),
                notes=notes, remind=remind,
            ),
        )
        return {"created_stage": compact(created)}

    @tool
    async def mark_lot_sown(lot_id: str, sown_on: Optional[str] = None) -> dict:
        """A planned lot was sown: plants it, logs the sowing, discounts its seed lot, closes its "Sembrar" task and
        generates its stage plan."""
        lot = await deps.planning.lot_sown(
            ctx.actor, UUID(lot_id), LotSown(sown_on=parse_date(sown_on) if sown_on else None)
        )
        return {"lot": compact(lot)}

    @tool
    async def archive_plan(plan_id: str) -> dict:
        """Archive a plan that is over or abandoned; its pending reminders are cancelled."""
        plan = await deps.planning.update_plan(ctx.actor, UUID(plan_id), PlanUpdate(status="archivado"))
        return {"plan": compact(plan)}

    @tool
    async def remove_reminder(reminder_id: str) -> dict:
        """Delete a reminder. Only after the user confirmed which one in a message of their own."""
        await deps.planning.delete_reminder(ctx.actor, UUID(reminder_id))
        return {"deleted_reminder_id": reminder_id}

    return [
        generate_crop_stage_plan,
        create_plan,
        add_plan_crops,
        add_plan_stage,
        mark_lot_sown,
        archive_plan,
        remove_reminder,
    ]
