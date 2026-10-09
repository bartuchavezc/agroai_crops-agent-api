"""Planning tools: reminders (agenda) and crop plans — the same data the web's Planificación tab edits.

Reminders are notified in-app when due (a batch job). A crop cycle's stage plan (germinación, traspaso,
etapas clave, posible cosecha) comes from its crop's template; a long plan (permaculture-style roadmap)
holds stages and staggered sowings that split a seed lot over time, each sowing with its own reminder."""
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from src.application.planning.schemas import (
    PlanCreate,
    PlanUpdate,
    ReminderCreate,
    ReminderUpdate,
    SowingCreate,
    SowRequest,
    StaggeredSowingCreate,
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
        days_ahead: int = 14, include_done: bool = False, field: Optional[str] = None, zone: Optional[str] = None
    ) -> dict:
        """The agenda: pending reminders up to `days_ahead` days from now, overdue ones included (due_at in the
        past and still pending). include_done also lists the ones already done. zone: only that zone's, e.g.
        'cantero 3'."""
        target = await resolve_field(deps, ctx, field) if (field or zone) else None
        zone_id = (await resolve_zone(deps, ctx, target, zone)).id if zone else None
        until = utcnow() + timedelta(days=max(1, min(days_ahead, 366)))
        items = await deps.planning.list_reminders(
            ctx.actor, status=None if include_done else "pendiente", until=until,
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
        crop_cycle_id: Optional[str] = None,
        recurrence: str = "none",
        every_days: Optional[int] = None,
        until: Optional[str] = None,
        assignee: Optional[str] = None,
    ) -> dict:
        """Schedule a reminder; it arrives as an in-app notification at `when` (YYYY-MM-DD = 09:00, or
        YYYY-MM-DDTHH:MM local). recurrence: none|daily|weekly|every_n_days (with every_days), optionally
        until YYYY-MM-DD. assignee: member name/email or "yo" (default: everyone in the account)."""
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
                crop_cycle_id=UUID(crop_cycle_id) if crop_cycle_id else None,
                **await _where(deps, ctx, field, zone),
            ),
        )
        return {"created_reminder": compact(reminder)}

    @tool
    async def complete_reminder(reminder_id: str) -> dict:
        """Mark a reminder done (a recurring one moves on to its next occurrence)."""
        return {"reminder": compact(await deps.planning.complete_reminder(ctx.actor, UUID(reminder_id)))}

    @tool
    async def postpone_reminder(reminder_id: str, when: str) -> dict:
        """Move a reminder to another date/time (YYYY-MM-DD = 09:00, or YYYY-MM-DDTHH:MM)."""
        updated = await deps.planning.update_reminder(
            ctx.actor, UUID(reminder_id), ReminderUpdate(due_at=_when(when, ctx, deps))
        )
        return {"reminder": compact(updated)}

    @tool
    async def list_plans(field: Optional[str] = None, include_archived: bool = False) -> dict:
        """Crop plans of the account: per crop cycle (kind ciclo) and long roadmaps (kind largo)."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        plans = await deps.planning.list_plans(ctx.actor, field_id=field_id)
        if not include_archived:
            plans = [p for p in plans if p.status != "archivado"]
        return {"plans": compact(plans)}

    @tool
    async def get_plan(plan_id: str) -> dict:
        """A plan with its stages, planned sowings and reminders."""
        return {"plan": compact(await deps.planning.get_plan(ctx.actor, UUID(plan_id)))}

    @tool
    async def preview_crop_stage_plan(crop_cycle_id: str) -> dict:
        """Proposed stages + reminders for a crop cycle from its crop's typical timeline (germinación,
        traspaso, etapas clave, posible cosecha). Nothing is saved: show it and offer generate_crop_stage_plan."""
        return {"proposal": compact(await deps.planning.propose_cycle_plan(ctx.actor, UUID(crop_cycle_id)))}

    return [
        list_reminders,
        add_reminder,
        complete_reminder,
        postpone_reminder,
        list_plans,
        get_plan,
        preview_crop_stage_plan,
    ]


def planning_manager_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    """Plans, stages and sowings: owner / tecnico."""

    @tool
    async def generate_crop_stage_plan(crop_cycle_id: str) -> dict:
        """Save a crop cycle's stage plan and its reminders (germinación, traspaso, etapas clave, posible
        cosecha, cosecha estimada). Regenerating replaces what was generated before."""
        result = await deps.planning.apply_cycle_plan(ctx.actor, UUID(crop_cycle_id))
        return {"applied": compact(result)}

    @tool
    async def create_plan(
        name: str,
        kind: str = "largo",
        field: Optional[str] = None,
        zone: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        notes: Optional[str] = None,
        stages: Optional[list[dict]] = None,
        sowings: Optional[list[dict]] = None,
    ) -> dict:
        """Create a plan. kind: largo (roadmap of seasons/years: perennials, guilds, staggered sowings) or
        ciclo. stages: [{name, stage: germinacion|plantin|traspaso|vegetativo|floracion|fructificacion|cosecha|
        establecimiento|poda|descanso|otro, start_date, end_date?, remind?: bool}]. sowings: [{crop, sow_date,
        zone?, quantity?, unit?}] — each sowing gets a reminder on its date. Dates YYYY-MM-DD."""
        where = await _where(deps, ctx, field, zone)
        stage_rows = [
            StageCreate(
                name=s["name"],
                stage=s.get("stage", "otro"),
                start_date=parse_date(s["start_date"]),
                end_date=parse_date(s.get("end_date")),
                notes=s.get("notes"),
                remind=bool(s.get("remind", False)),
            )
            for s in (stages or [])
        ]
        sowing_rows = []
        for s in sowings or []:
            sowing_where = await _where(deps, ctx, field, s.get("zone")) if s.get("zone") else {}
            sowing_rows.append(
                SowingCreate(
                    crop_master_id=await _crop_id(deps, ctx, s["crop"]),
                    sow_date=parse_date(s["sow_date"]),
                    zone_id=sowing_where.get("zone_id") or where.get("zone_id"),
                    quantity=s.get("quantity"),
                    unit=s.get("unit"),
                    notes=s.get("notes"),
                )
            )
        plan = await deps.planning.create_plan(
            ctx.actor,
            PlanCreate(
                name=name,
                kind=kind,
                start_date=parse_date(start_date),
                end_date=parse_date(end_date),
                notes=notes,
                stages=stage_rows,
                sowings=sowing_rows,
                **where,
            ),
        )
        return {"created_plan": compact(plan)}

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
    async def plan_staggered_sowing(
        plan_id: str,
        crop: str,
        start_date: str,
        count: int,
        every_days: int,
        zone: Optional[str] = None,
        field: Optional[str] = None,
        total_quantity: Optional[float] = None,
        unit: Optional[str] = None,
        use_seed_lot: bool = False,
    ) -> dict:
        """Split a sowing over time: `count` sowings of `crop`, one every `every_days` from start_date,
        dividing total_quantity (seeds, gramos, plantines) evenly — e.g. lettuce every 15 days for continuous
        harvest. Each sowing gets a reminder. use_seed_lot: take the seed from the crop's lot in inventory
        (discounted when the sowing is marked done)."""
        crop_id = await _crop_id(deps, ctx, crop)
        where = await _where(deps, ctx, field, zone) if zone else {}
        lot_id = None
        if use_seed_lot:
            lots = await deps.inventory.list_seed_lots(ctx.actor, crop_master_id=crop_id)
            if not lots:
                raise InvalidInputError("There is no seed lot of that crop in inventory.")
            lot_id = lots[0].id
            unit = unit or lots[0].unit
        sowings = await deps.planning.add_staggered_sowings(
            ctx.actor,
            UUID(plan_id),
            StaggeredSowingCreate(
                crop_master_id=crop_id,
                start_date=parse_date(start_date),
                count=count,
                every_days=every_days,
                zone_id=where.get("zone_id"),
                total_quantity=total_quantity,
                unit=unit,
                seed_lot_id=lot_id,
            ),
        )
        return {"created_sowings": compact(sowings)}

    @tool
    async def mark_sowing_done(sowing_id: str, sown_on: Optional[str] = None) -> dict:
        """A planned sowing happened: starts its crop cycle (with its stage reminders) and discounts the seed."""
        sowing = await deps.planning.sow(
            ctx.actor, UUID(sowing_id), SowRequest(sown_on=parse_date(sown_on) if sown_on else None)
        )
        return {"sowing": compact(sowing)}

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
        add_plan_stage,
        plan_staggered_sowing,
        mark_sowing_done,
        archive_plan,
        remove_reminder,
    ]
