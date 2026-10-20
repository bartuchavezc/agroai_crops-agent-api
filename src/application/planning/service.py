"""
Planning: reminders (one-off or recurring notices, sent in-app by the `reminders` batch job), crop plans — general
ones with objectives, zones and crops (once, staggered or perennial: each sowing a planned lot with its "Sembrar"
task) — and the stage plan of a lot generated from its crop's template
(germinación -> traspaso -> etapas clave -> posible cosecha).

Permissions: every member can create reminders (staff does the daily work); plans, stages and plan crops are
manager-only, like lots. Reminders without assignee notify the whole account.
"""
from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.application.farm.schemas import FieldEventCreate, LotCreate, LotRead, LotUpdate
from src.application.tasks.schemas import TaskCreate, TaskUpdate
from src.shared.domain.locale import localized
from src.shared.domain.messages import adapt
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .calendar import (
    CalendarItem,
    CalendarRange,
    CalendarResponse,
)
from .calendar import occurrences as calendar_occurrences
from .models import CropPlan, PlanCrop, PlanStage, Reminder
from .repository import IdFilter, PlanningRepository
from .schemas import (
    CyclePlanProposal,
    PlanCreate,
    PlanDetail,
    PlanRead,
    PlanUpdate,
    ProposedReminder,
    ProposedStage,
    ReminderCreate,
    ReminderRead,
    ReminderUpdate,
    LotSown,
    PlanCropCreate,
    PlanCropRead,
    StageCreate,
    StageRead,
    StageUpdate,
)
from .stage_templates import harvest_window_days, template_for

MAX_CALENDAR_DAYS = 400  # a year view
REMINDER_HOUR = time(9, 0)  # date-only reminders go off at 09:00 local time


def _require_manager(actor: Actor) -> None:
    if not actor.is_manager:
        raise PermissionDeniedError("Only owner or tecnico can do this.")


def _step(reminder: Reminder) -> Optional[timedelta]:
    return {
        "daily": timedelta(days=1),
        "weekly": timedelta(days=7),
        "every_n_days": timedelta(days=reminder.interval_days or 1),
    }.get(reminder.recurrence)


def next_occurrence(reminder: Reminder, after: datetime) -> Optional[datetime]:
    """First occurrence of a recurring reminder strictly after `after`; None if the series is over."""
    step = _step(reminder)
    if step is None:
        return None
    nxt = reminder.due_at
    while nxt <= after:
        nxt += step
    if reminder.until and nxt.date() > reminder.until:
        return None
    return nxt


class PlanningService:
    def __init__(
        self,
        repository: PlanningRepository,
        farm_service,
        notification_service,
        management_service,
        inventory_service,
        timezone_name: str,
        task_service=None,
    ):
        self.repo = repository
        self.farm = farm_service
        self.notifications = notification_service
        self.management = management_service
        self.inventory = inventory_service
        self.tz = ZoneInfo(timezone_name)
        self.tasks = task_service
        if task_service is not None:  # finishing a planned lot's "Sembrar" task sows the lot
            task_service.lot_sown_hook = lambda actor, lot_id: self.lot_sown(actor, lot_id, from_task=True)

    def _tz(self, actor: Actor) -> ZoneInfo:
        """The user's own zone (a Colombian's 09:00 reminder is not 09:00 in Buenos Aires); the app's if unknown."""
        try:
            return ZoneInfo(actor.timezone) if actor.timezone else self.tz
        except (ZoneInfoNotFoundError, ValueError, OSError):
            return self.tz

    def at_local(self, day: date, at: time = REMINDER_HOUR, tz: Optional[ZoneInfo] = None) -> datetime:
        return datetime.combine(day, at, tzinfo=tz or self.tz)

    def _aware(self, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=self.tz)

    async def _check_refs(self, actor: Actor, values: dict) -> None:
        if values.get("field_id"):
            await self.farm.get_field(actor, values["field_id"])
        if values.get("zone_id"):
            zone = await self.farm.get_zone(actor, values["zone_id"])
            if values.get("field_id") and zone.field_id != values["field_id"]:
                raise InvalidInputError("The zone does not belong to that field.")
        if values.get("lot_id"):
            await self.farm.get_lot(actor, values["lot_id"])
        if values.get("crop_master_id"):
            await self.farm.get_crop_master(actor, values["crop_master_id"])
        if values.get("assigned_to"):
            await self.management._check_assignee(actor, values["assigned_to"])
        if values.get("plan_id"):
            await self._plan(actor, values["plan_id"])
        if values.get("seed_lot_id"):
            lots = await self.inventory.list_seed_lots(actor)
            if not any(lot.id == values["seed_lot_id"] for lot in lots):
                raise NotFoundError(f"Seed lot {values['seed_lot_id']} not found.")

    # ---------- reminders ----------

    async def list_reminders(
        self,
        actor: Actor,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        field_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
        plan_id: Optional[UUID] = None,
        assigned_to: IdFilter = None,
        limit: int = 200,
        zone_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
    ) -> list[ReminderRead]:
        rows = await self.repo.list_reminders(
            actor.account_id, status, since, until, field_id, lot_id, plan_id, assigned_to, min(limit, 500),
            zone_id=zone_id, before=before,
        )
        return [ReminderRead.model_validate(r) for r in rows]

    async def get_reminder(self, actor: Actor, reminder_id: UUID) -> Reminder:
        reminder = await self.repo.get(Reminder, actor.account_id, reminder_id)
        if reminder is None:
            raise NotFoundError(f"Reminder {reminder_id} not found.")
        return reminder

    async def create_reminder(self, actor: Actor, data: ReminderCreate, source: Optional[str] = None) -> ReminderRead:
        values = data.model_dump()
        await self._check_refs(actor, values)
        reminder = Reminder(
            account_id=actor.account_id,
            created_by=actor.user_id,
            source=source or ("agent" if actor.via == "agent" else "user"),
            **{**values, "due_at": self._aware(data.due_at)},
        )
        await self.repo.add(reminder)
        return ReminderRead.model_validate(reminder)

    async def update_reminder(self, actor: Actor, reminder_id: UUID, data: ReminderUpdate) -> ReminderRead:
        current = await self.get_reminder(actor, reminder_id)
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        if "due_at" in values:
            values["due_at"] = self._aware(values["due_at"])
            values["notified_at"] = None  # rescheduled: its new occurrence is notified again
        recurrence = values.get("recurrence", current.recurrence)
        if recurrence == "every_n_days" and not values.get("interval_days", current.interval_days):
            raise InvalidInputError("every_n_days needs interval_days.")
        if values.get("status") == "activo" and current.status == "terminado" and "due_at" not in values:
            raise InvalidInputError("To reactivate a finished reminder, give it a new due_at.")
        reminder = await self.repo.update(Reminder, actor.account_id, reminder_id, values)
        return ReminderRead.model_validate(reminder)

    async def delete_reminder(self, actor: Actor, reminder_id: UUID) -> None:
        reminder = await self.get_reminder(actor, reminder_id)
        if not actor.is_manager and reminder.created_by != actor.user_id:
            raise PermissionDeniedError("You can only delete reminders you created.")
        await self.repo.remove(Reminder, actor.account_id, reminder_id)

    async def run_due_reminders(self, now: Optional[datetime] = None) -> dict:
        """Batch job: notify every due occurrence once; recurring reminders move on to the next one."""
        now = now or utcnow()
        sent = 0
        for reminder in await self.repo.due_reminders(now):
            when = reminder.due_at.astimezone(self.tz)
            await self.notifications.notify_account(
                account_id=reminder.account_id,
                exclude_user_id=None,
                only_user_id=reminder.assigned_to,
                type="reminder",
                title=reminder.title,
                message=reminder.description or f"Recordatorio para el {when:%d/%m %H:%M}",
                entity_type="reminder",
                entity_id=reminder.id,
                field_id=reminder.field_id,
                zone_id=reminder.zone_id,
                lot_id=reminder.lot_id,
            )
            values: dict = {"notified_at": now}
            if reminder.recurrence != "none":
                nxt = next_occurrence(reminder, now)
                values.update({"due_at": nxt} if nxt else {"status": "terminado"})
            else:
                values["status"] = "terminado"
            await self.repo.update(Reminder, reminder.account_id, reminder.id, values)
            sent += 1
        return {"notified": sent}

    async def calendar(
        self, actor: Actor, since: date, until: date, field_id: Optional[UUID] = None
    ) -> CalendarResponse:
        """Everything planned in [since, until] (inclusive dates, the user's zone): reminders with their recurrences
        expanded, planned sowings, and the stages of active plans (as items on their start day and as ranges)."""
        if until < since:
            raise InvalidInputError("`until` must not be before `since`.")
        if (until - since).days > MAX_CALENDAR_DAYS:
            raise InvalidInputError(f"The calendar covers at most {MAX_CALENDAR_DAYS} days at a time.")
        if field_id:
            await self.farm.get_field(actor, field_id)
        tz = self._tz(actor)
        since_dt = datetime.combine(since, time.min, tzinfo=tz)
        until_dt = datetime.combine(until + timedelta(days=1), time.min, tzinfo=tz)
        stages, sowings, reminders = await self.repo.calendar_rows(
            actor.account_id, since, until, since_dt, until_dt, field_id
        )
        items: list[CalendarItem] = []
        for reminder in reminders:
            for when in calendar_occurrences(
                reminder.due_at, reminder.recurrence, reminder.interval_days, reminder.until, since_dt, until_dt, tz
            ):
                items.append(CalendarItem(
                    date=when.date(), kind="reminder", source=reminder.source, ref_id=reminder.id,
                    title=reminder.title, due_at=when, recurring=reminder.recurrence != "none",
                    field_id=reminder.field_id, zone_id=reminder.zone_id, status=reminder.status,
                ))
        for lot, plan, crop in sowings:  # the lots plans sow in the window (ref_id: the lot)
            items.append(CalendarItem(
                date=lot.planting_date, kind="sowing", source=plan.source, ref_id=lot.id,
                title=f"Sembrar {localized(crop.name, crop.i18n, actor.locale)}", field_id=lot.field_id,
                zone_id=plan.zone_id, status=lot.status,
            ))
        ranges: list[CalendarRange] = []
        for stage, plan in stages:
            title = adapt(stage.name, actor.locale)
            end = stage.end_date or stage.start_date
            if since <= stage.start_date <= until:
                items.append(CalendarItem(
                    date=stage.start_date, kind="stage", source=stage.source, ref_id=stage.id, title=title,
                    stage=stage.stage, field_id=plan.field_id, zone_id=stage.zone_id or plan.zone_id,
                ))
            ranges.append(CalendarRange(
                start=stage.start_date, end=end, ref_id=stage.id, plan_id=plan.id, title=title, stage=stage.stage,
                field_id=plan.field_id, zone_id=stage.zone_id or plan.zone_id,
            ))
        items.sort(key=lambda i: (i.date, i.due_at or datetime.min.replace(tzinfo=tz), i.kind))
        return CalendarResponse(since=since, until=until, items=items, ranges=ranges)

    async def _plan(self, actor: Actor, plan_id: UUID) -> CropPlan:
        plan = await self.repo.get(CropPlan, actor.account_id, plan_id)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        return plan

    async def _plan_reads(self, plans) -> list[PlanRead]:
        plans = list(plans)
        zones = await self.repo.plan_zone_ids([p.id for p in plans])
        return [PlanRead.model_validate(p).model_copy(update={"zone_ids": zones.get(p.id, [])}) for p in plans]

    async def list_plans(
        self, actor: Actor, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> list[PlanRead]:
        return await self._plan_reads(await self.repo.list_plans(actor.account_id, field_id, status))

    async def get_plan(self, actor: Actor, plan_id: UUID) -> PlanDetail:
        plan = await self._plan(actor, plan_id)
        stages, crops, reminders = await self.repo.plan_children(plan.id)
        lots = [lot for lot in await self.farm.list_lots(actor, field_id=plan.field_id) if lot.plan_id == plan.id] \
            if plan.field_id else []
        tasks = await self.tasks.list_tasks(actor, plan_id=plan.id) if self.tasks is not None else []
        return PlanDetail(
            **(await self._plan_reads([plan]))[0].model_dump(),
            stages=[StageRead.model_validate(s) for s in stages],
            crops=[PlanCropRead.model_validate(c) for c in crops],
            lots=sorted(lots, key=lambda lot: (lot.planting_date or date.max, lot.created_at)),
            tasks=tasks,
            reminders=[ReminderRead.model_validate(r) for r in reminders],
        )

    async def _plan_zones(self, actor: Actor, zone_ids: list[UUID], field_id: Optional[UUID]) -> Optional[UUID]:
        """Checks the zones (all of one field, the plan's if it has one) and returns that field."""
        for zone_id in zone_ids:
            zone = await self.farm.get_zone(actor, zone_id)
            if field_id and zone.field_id != field_id:
                raise InvalidInputError("Every zone of the plan must be in its field.")
            field_id = zone.field_id
        return field_id

    async def create_plan(self, actor: Actor, data: PlanCreate) -> PlanDetail:
        _require_manager(actor)
        values = data.model_dump(exclude={"stages", "crops", "zone_ids"})
        await self._check_refs(actor, values)
        if data.zone_id and not data.field_id:
            values["field_id"] = (await self.farm.get_zone(actor, data.zone_id)).field_id
        values["field_id"] = await self._plan_zones(actor, data.zone_ids, values.get("field_id"))
        plan = CropPlan(
            account_id=actor.account_id,
            created_by=actor.user_id,
            source="agent" if actor.via == "agent" else "user",
            **values,
        )
        await self.repo.add(plan)
        if data.zone_ids:
            await self.repo.set_plan_zones(plan.id, data.zone_ids)
        for stage in data.stages:
            await self.add_stage(actor, plan.id, stage)
        for crop in data.crops:
            await self.add_plan_crop(actor, plan.id, crop)
        return await self.get_plan(actor, plan.id)

    async def update_plan(self, actor: Actor, plan_id: UUID, data: PlanUpdate) -> PlanRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True, exclude={"zone_ids"})
        await self._check_refs(actor, values)
        current = await self._plan(actor, plan_id)
        if data.zone_ids is not None:
            field_id = await self._plan_zones(actor, data.zone_ids, values.get("field_id", current.field_id))
            if field_id and not values.get("field_id", current.field_id):
                values["field_id"] = field_id
        plan = await self.repo.update(CropPlan, actor.account_id, plan_id, values)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        if data.zone_ids is not None:
            await self.repo.set_plan_zones(plan_id, data.zone_ids)
        if values.get("status") == "archivado":
            await self.repo.cancel_plan_reminders(actor.account_id, plan_id)
            if self.tasks is not None:
                await self.tasks.cancel_plan_tasks(actor, plan_id)
        return (await self._plan_reads([plan]))[0]

    async def delete_plan(self, actor: Actor, plan_id: UUID) -> None:
        _require_manager(actor)
        await self._plan(actor, plan_id)
        await self.repo.cancel_plan_reminders(actor.account_id, plan_id)
        if self.tasks is not None:
            await self.tasks.cancel_plan_tasks(actor, plan_id)
        await self.repo.remove(CropPlan, actor.account_id, plan_id)

    # ---------- stages ----------

    async def add_stage(self, actor: Actor, plan_id: UUID, data: StageCreate, source: str = "user") -> StageRead:
        _require_manager(actor)
        plan = await self._plan(actor, plan_id)
        values = data.model_dump(exclude={"remind"})
        await self._check_refs(actor, values)
        stages, _, _ = await self.repo.plan_children(plan.id)
        stage = PlanStage(account_id=actor.account_id, plan_id=plan.id, position=len(stages), source=source, **values)
        await self.repo.add(stage)
        if data.remind:
            await self.repo.add(
                Reminder(
                    account_id=actor.account_id,
                    plan_id=plan.id,
                    stage_id=stage.id,
                    lot_id=data.lot_id or plan.lot_id,
                    field_id=plan.field_id,
                    zone_id=data.zone_id or plan.zone_id,
                    title=f"{plan.name}: {data.name}",
                    description=data.notes,
                    due_at=self.at_local(data.start_date, tz=self._tz(actor)),
                    source="plan",
                    created_by=actor.user_id,
                )
            )
        return StageRead.model_validate(stage)

    async def update_stage(self, actor: Actor, stage_id: UUID, data: StageUpdate) -> StageRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        stage = await self.repo.update(PlanStage, actor.account_id, stage_id, values)
        if stage is None:
            raise NotFoundError(f"Stage {stage_id} not found.")
        return StageRead.model_validate(stage)

    async def delete_stage(self, actor: Actor, stage_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.remove(PlanStage, actor.account_id, stage_id):
            raise NotFoundError(f"Stage {stage_id} not found.")

    # ---------- plan crops: planned lots and their sowing tasks ----------

    async def add_plan_crop(self, actor: Actor, plan_id: UUID, data: PlanCropCreate) -> PlanCropRead:
        """Each sowing of the crop becomes a planned lot (in its zones, or the plan's) with a "Sembrar" task."""
        _require_manager(actor)
        plan = await self._plan(actor, plan_id)
        values = data.model_dump()
        await self._check_refs(actor, {"crop_master_id": data.crop_master_id, "seed_lot_id": data.seed_lot_id})
        zone_ids = data.zone_ids or (await self.repo.plan_zone_ids([plan.id])).get(plan.id) or (
            [plan.zone_id] if plan.zone_id else []
        )
        zones = [await self.farm.get_zone(actor, z) for z in zone_ids]
        field_id = plan.field_id or (zones[0].field_id if zones else None)
        if not field_id:
            raise InvalidInputError("The plan has no field: set one (or zones) to plan its crops.")
        if any(z.field_id != field_id for z in zones):
            raise InvalidInputError("Every zone must be in the plan's field.")
        crop = await self.farm.get_crop_master(actor, data.crop_master_id)
        plan_crop = PlanCrop(
            account_id=actor.account_id, plan_id=plan.id, **{**values, "zone_ids": [str(z) for z in zone_ids]}
        )
        await self.repo.add(plan_crop)
        crop_name = f"{localized(crop.name, crop.i18n, actor.locale)}{' ' + crop.variety if crop.variety else ''}"
        where = " + ".join(z.label for z in zones)
        for i in range(data.count):
            sow_on = data.start_date + timedelta(days=i * (data.every_days or 0))
            lot = await self.farm.create_lot(
                actor,
                LotCreate(
                    field_id=field_id, crop_master_id=data.crop_master_id, zone_ids=zone_ids, status="planned",
                    planting_date=sow_on, quantity=data.quantity, unit=data.unit, plan_id=plan.id,
                    plan_crop_id=plan_crop.id,
                    expected_harvest_date=sow_on + timedelta(days=crop.growth_period_days)
                    if crop.growth_period_days and data.mode != "perennial" else None,
                    notes=data.notes or (f"Siembra {i + 1} de {data.count} de «{plan.name}»" if data.count > 1
                                         else f"Plan «{plan.name}»"),
                ),
            )
            if self.tasks is not None:
                amount = f" ({data.quantity:g} {data.unit or ''})".rstrip() if data.quantity else ""
                await self.tasks.create_task(
                    actor,
                    TaskCreate(
                        title=f"Sembrar {crop_name}{amount}" + (f" en {where}" if where else ""),
                        description=f"Siembra planificada en «{plan.name}».", field_id=field_id,
                        zone_id=zone_ids[0] if len(zone_ids) == 1 else None, lot_id=lot.id, plan_id=plan.id,
                        due_date=sow_on, result_event_type="sowing",
                    ),
                    source="plan",
                )
        return PlanCropRead.model_validate(plan_crop)

    async def delete_plan_crop(self, actor: Actor, crop_id: UUID) -> None:
        """Drops a crop from the plan with the lots it planned and not yet sown (and their open tasks)."""
        _require_manager(actor)
        plan_crop = await self.repo.get(PlanCrop, actor.account_id, crop_id)
        if plan_crop is None:
            raise NotFoundError(f"Plan crop {crop_id} not found.")
        for lot in await self.farm.list_lots(actor, statuses=["planned"]):
            if lot.plan_crop_id == crop_id:
                if self.tasks is not None:
                    for task in await self.tasks.list_tasks(actor, lot_id=lot.id, open_only=True):
                        await self.tasks.update_task(actor, task.id, TaskUpdate(status="cancelada"))
                await self.farm.delete_lot(actor, lot.id)
        await self.repo.delete_plan_crop(actor.account_id, crop_id)

    async def lot_sown(
        self, actor: Actor, lot_id: UUID, data: Optional[LotSown] = None, from_task: bool = False
    ) -> LotRead:
        """A planned lot was sown: it is planted (on `sown_on`), logged in the bitácora, its seed comes off the seed
        lot of its plan crop, its "Sembrar" task is done and its stage plan generated. Finishing that task does the
        same (`from_task`: the task already logged the sowing)."""
        _require_manager(actor)
        data = data or LotSown()
        lot = await self.farm.get_lot(actor, lot_id)
        if lot.status != "planned":
            raise InvalidInputError("That lot is already sown.")
        sown_on = data.sown_on or utcnow().astimezone(self._tz(actor)).date()
        lot = await self.farm.update_lot(actor, lot_id, LotUpdate(status="planted", planting_date=sown_on))
        if not from_task:
            await self.farm.create_event(
                actor,
                FieldEventCreate(
                    field_id=lot.field_id, zone_id=lot.zone_id, lot_ids=[lot.id], type="sowing",
                    occurred_at=self.at_local(sown_on, tz=self._tz(actor)), quantity=lot.quantity, unit=lot.unit,
                ),
            )
        if data.consume_seed_lot and lot.plan_crop_id and lot.quantity:
            plan_crop = await self.repo.get(PlanCrop, actor.account_id, lot.plan_crop_id)
            if plan_crop is not None and plan_crop.seed_lot_id:
                await self.inventory.consume_seed_lot(actor, plan_crop.seed_lot_id, lot.quantity, lot.unit)
        if self.tasks is not None and not from_task:
            for task in await self.tasks.list_tasks(actor, lot_id=lot_id, open_only=True):
                if task.result_event_type == "sowing":
                    await self.tasks.repo.update(
                        actor.account_id, task.id, {"status": "hecha", "completed_at": utcnow()}
                    )
        await self.apply_cycle_plan(actor, lot_id)
        return await self.farm.get_lot(actor, lot_id)

    # ---------- lot stage plan ----------

    async def propose_cycle_plan(self, actor: Actor, cycle_id: UUID) -> CyclePlanProposal:
        """Stages and reminders for a lot from its crop's template: emergence, transplant, key
        milestones, "posible cosecha" and the expected harvest. Nothing is saved."""
        cycle = await self.farm.get_lot(actor, cycle_id)
        crop = await self.farm.get_crop_master(actor, cycle.crop_master_id)
        crop_name = f"{localized(crop.name, crop.i18n, actor.locale)}{' ' + crop.variety if crop.variety else ''}"
        sowing = cycle.planting_date or utcnow().astimezone(self._tz(actor)).date()
        tpl = template_for(crop.name, crop.growth_period_days)
        period = crop.growth_period_days or 90
        harvest = cycle.expected_harvest_date or sowing + timedelta(days=period)
        harvest_start = harvest - timedelta(days=harvest_window_days(period))
        day = lambda n: sowing + timedelta(days=n)  # noqa: E731

        # Points in time where a stage begins (days after sowing), with their reminder.
        points: list[tuple[date, str, str, Optional[str]]] = [
            (sowing, "germinacion", "Germinación", None),
            (day(tpl.emergence_days),
             "plantin" if tpl.transplant_day else "vegetativo",
             "Plantín en almácigo" if tpl.transplant_day else "Crecimiento",
             f"Revisar germinación de {crop_name}"),
        ]
        if tpl.transplant_day:
            points.append((day(tpl.transplant_day), "vegetativo", "Crecimiento tras el traspaso",
                           f"Traspasar {crop_name} a su lugar definitivo"))
        for m in tpl.milestones:
            if day(m.day) < harvest_start:
                points.append((day(m.day), m.stage, m.name, f"{crop_name}: {m.reminder}"))
        points.append((harvest_start, "cosecha", "Posible cosecha", f"Posible cosecha de {crop_name}: revisar punto"))
        points.sort(key=lambda p: p[0])
        points = [(d, st, adapt(n, actor.locale), adapt(t, actor.locale) if t else t) for d, st, n, t in points]

        stages = [
            ProposedStage(
                name=name,
                stage=stage,
                start_date=start,
                end_date=points[i + 1][0] if i + 1 < len(points) else harvest,
            )
            for i, (start, stage, name, _) in enumerate(points)
        ]
        today = utcnow().astimezone(self._tz(actor)).date()
        reminders = [
            ProposedReminder(title=text, due_at=self.at_local(start, tz=self._tz(actor)), description=f"Etapa: {name}")
            for start, _, name, text in points
            if text and start >= today
        ]
        if harvest >= today:
            reminders.append(
                ProposedReminder(
                    title=f"Cosecha estimada de {crop_name}", due_at=self.at_local(harvest, tz=self._tz(actor))
                )
            )
        return CyclePlanProposal(
            lot_id=cycle.id,
            crop_name=crop_name,
            sowing_date=sowing,
            expected_harvest_date=harvest,
            stages=stages,
            reminders=reminders,
        )

    async def apply_cycle_plan(self, actor: Actor, cycle_id: UUID) -> CyclePlanProposal:
        """Save the proposal as the cycle's plan (replacing what was generated before; done reminders stay)."""
        _require_manager(actor)
        proposal = await self.propose_cycle_plan(actor, cycle_id)
        cycle = await self.farm.get_lot(actor, cycle_id)
        existing = await self.repo.list_plans(actor.account_id, lot_id=cycle_id)
        if existing:
            plan = existing[0]
            await self.repo.clear_generated(plan.id)
        else:
            where = (await self.farm.get_zone(actor, cycle.zone_id)).label if cycle.zone_id else None
            plan = CropPlan(
                account_id=actor.account_id,
                field_id=cycle.field_id,
                zone_id=cycle.zone_id,
                lot_id=cycle.id,
                name=f"{proposal.crop_name}{' — ' + where if where else ''}",
                kind="ciclo",
                start_date=proposal.sowing_date,
                end_date=proposal.expected_harvest_date,
                source="agent" if actor.via == "agent" else "user",
                created_by=actor.user_id,
            )
            await self.repo.add(plan)
        stage_rows = [
            PlanStage(
                account_id=actor.account_id,
                plan_id=plan.id,
                crop_master_id=cycle.crop_master_id,
                lot_id=cycle.id,
                zone_id=cycle.zone_id,
                position=i,
                source="plan",
                **s.model_dump(),
            )
            for i, s in enumerate(proposal.stages)
        ]
        await self.repo.add(*stage_rows)
        stage_by_start = {s.start_date: s for s in stage_rows}
        await self.repo.add(
            *[
                Reminder(
                    account_id=actor.account_id,
                    plan_id=plan.id,
                    stage_id=getattr(stage_by_start.get(r.due_at.date()), "id", None),
                    lot_id=cycle.id,
                    field_id=cycle.field_id,
                    zone_id=cycle.zone_id,
                    title=r.title,
                    description=r.description,
                    due_at=r.due_at,
                    source="plan",
                    created_by=actor.user_id,
                )
                for r in proposal.reminders
            ]
        )
        return proposal.model_copy(update={"plan_id": plan.id})
