"""
Planning: reminders (one-off or recurring, notified in-app by the `reminders` batch job), crop plans with
stages and staggered sowings, and the stage plan of a crop cycle generated from its crop's template
(germinación -> traspaso -> etapas clave -> posible cosecha).

Permissions: every member can create and tick reminders (staff does the daily work); plans, stages and
sowings are manager-only, like crop cycles. Reminders without assignee notify the whole account.
"""
from datetime import date, datetime, time, timedelta
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from src.application.farm.schemas import CropCycleCreate
from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import CropPlan, PlanSowing, PlanStage, Reminder
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
    SowingCreate,
    SowingRead,
    SowingUpdate,
    SowRequest,
    StaggeredSowingCreate,
    StageCreate,
    StageRead,
    StageUpdate,
)
from .stage_templates import harvest_window_days, template_for

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
    ):
        self.repo = repository
        self.farm = farm_service
        self.notifications = notification_service
        self.management = management_service
        self.inventory = inventory_service
        self.tz = ZoneInfo(timezone_name)

    def at_local(self, day: date, at: time = REMINDER_HOUR) -> datetime:
        return datetime.combine(day, at, tzinfo=self.tz)

    def _aware(self, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=self.tz)

    async def _check_refs(self, actor: Actor, values: dict) -> None:
        if values.get("field_id"):
            await self.farm.get_field(actor, values["field_id"])
        if values.get("zone_id"):
            zone = await self.farm.get_zone(actor, values["zone_id"])
            if values.get("field_id") and zone.field_id != values["field_id"]:
                raise InvalidInputError("The zone does not belong to that field.")
        if values.get("crop_cycle_id"):
            await self.farm.get_crop_cycle(actor, values["crop_cycle_id"])
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
        crop_cycle_id: Optional[UUID] = None,
        plan_id: Optional[UUID] = None,
        assigned_to: IdFilter = None,
        limit: int = 200,
    ) -> list[ReminderRead]:
        rows = await self.repo.list_reminders(
            actor.account_id, status, since, until, field_id, crop_cycle_id, plan_id, assigned_to, min(limit, 500)
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
        recurrence = values.get("recurrence", current.recurrence)
        if recurrence == "every_n_days" and not values.get("interval_days", current.interval_days):
            raise InvalidInputError("every_n_days needs interval_days.")
        if values.get("status") == "hecho":
            values["completed_at"] = utcnow()
        elif values.get("status") == "pendiente":
            values["completed_at"] = None
        reminder = await self.repo.update(Reminder, actor.account_id, reminder_id, values)
        return ReminderRead.model_validate(reminder)

    async def complete_reminder(self, actor: Actor, reminder_id: UUID) -> ReminderRead:
        """Done. A recurring one moves on to its next occurrence (finishing the series after `until`)."""
        reminder = await self.get_reminder(actor, reminder_id)
        now = utcnow()
        nxt = next_occurrence(reminder, max(now, reminder.due_at))
        values = {"due_at": nxt} if nxt else {"status": "hecho", "completed_at": now}
        updated = await self.repo.update(Reminder, actor.account_id, reminder_id, values)
        return ReminderRead.model_validate(updated)

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
            )
            values: dict = {"notified_at": now}
            if reminder.recurrence != "none":
                nxt = next_occurrence(reminder, now)
                values.update({"due_at": nxt} if nxt else {"status": "hecho", "completed_at": now})
            await self.repo.update(Reminder, reminder.account_id, reminder.id, values)
            sent += 1
        return {"notified": sent}

    # ---------- plans ----------

    async def _plan(self, actor: Actor, plan_id: UUID) -> CropPlan:
        plan = await self.repo.get(CropPlan, actor.account_id, plan_id)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        return plan

    async def list_plans(
        self, actor: Actor, field_id: Optional[UUID] = None, status: Optional[str] = None
    ) -> list[PlanRead]:
        return [PlanRead.model_validate(p) for p in await self.repo.list_plans(actor.account_id, field_id, status)]

    async def get_plan(self, actor: Actor, plan_id: UUID) -> PlanDetail:
        plan = await self._plan(actor, plan_id)
        stages, sowings, reminders = await self.repo.plan_children(plan.id)
        return PlanDetail(
            **PlanRead.model_validate(plan).model_dump(),
            stages=[StageRead.model_validate(s) for s in stages],
            sowings=[SowingRead.model_validate(s) for s in sowings],
            reminders=[ReminderRead.model_validate(r) for r in reminders],
        )

    async def create_plan(self, actor: Actor, data: PlanCreate) -> PlanDetail:
        _require_manager(actor)
        values = data.model_dump(exclude={"stages", "sowings"})
        await self._check_refs(actor, values)
        if data.zone_id and not data.field_id:
            values["field_id"] = (await self.farm.get_zone(actor, data.zone_id)).field_id
        plan = CropPlan(
            account_id=actor.account_id,
            created_by=actor.user_id,
            source="agent" if actor.via == "agent" else "user",
            **values,
        )
        await self.repo.add(plan)
        for stage in data.stages:
            await self.add_stage(actor, plan.id, stage)
        for sowing in data.sowings:
            await self.add_sowing(actor, plan.id, sowing)
        return await self.get_plan(actor, plan.id)

    async def update_plan(self, actor: Actor, plan_id: UUID, data: PlanUpdate) -> PlanRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        plan = await self.repo.update(CropPlan, actor.account_id, plan_id, values)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found.")
        if values.get("status") == "archivado":
            await self.repo.cancel_plan_reminders(actor.account_id, plan_id)
        return PlanRead.model_validate(plan)

    async def delete_plan(self, actor: Actor, plan_id: UUID) -> None:
        _require_manager(actor)
        await self._plan(actor, plan_id)
        await self.repo.cancel_plan_reminders(actor.account_id, plan_id)
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
                    crop_cycle_id=data.crop_cycle_id or plan.crop_cycle_id,
                    field_id=plan.field_id,
                    zone_id=data.zone_id or plan.zone_id,
                    title=f"{plan.name}: {data.name}",
                    description=data.notes,
                    due_at=self.at_local(data.start_date),
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

    # ---------- sowings ----------

    async def _sowing_reminder(self, actor: Actor, plan: CropPlan, sowing: PlanSowing) -> Reminder:
        crop = await self.farm.get_crop_master(actor, sowing.crop_master_id)
        where = (await self.farm.get_zone(actor, sowing.zone_id)).label if sowing.zone_id else None
        amount = f" ({sowing.quantity:g} {sowing.unit or ''})".rstrip() if sowing.quantity else ""
        title = f"Sembrar {crop.name}{' ' + crop.variety if crop.variety else ''}{amount}"
        return Reminder(
            account_id=actor.account_id,
            plan_id=plan.id,
            sowing_id=sowing.id,
            field_id=plan.field_id,
            zone_id=sowing.zone_id or plan.zone_id,
            title=f"{title} en {where}" if where else title,
            description=f"Siembra planificada en «{plan.name}».",
            due_at=self.at_local(sowing.sow_date),
            source="plan",
            created_by=actor.user_id,
        )

    async def add_sowing(self, actor: Actor, plan_id: UUID, data: SowingCreate) -> SowingRead:
        _require_manager(actor)
        plan = await self._plan(actor, plan_id)
        values = data.model_dump()
        await self._check_refs(actor, values)
        sowing = PlanSowing(account_id=actor.account_id, plan_id=plan.id, **values)
        await self.repo.add(sowing)
        await self.repo.add(await self._sowing_reminder(actor, plan, sowing))
        return SowingRead.model_validate(sowing)

    async def add_staggered_sowings(self, actor: Actor, plan_id: UUID, data: StaggeredSowingCreate) -> list[SowingRead]:
        """Divide a sowing (and its seed) over time: count sowings, one every every_days."""
        each = round(data.total_quantity / data.count, 2) if data.total_quantity else None
        return [
            await self.add_sowing(
                actor,
                plan_id,
                SowingCreate(
                    crop_master_id=data.crop_master_id,
                    sow_date=data.start_date + timedelta(days=i * data.every_days),
                    zone_id=data.zone_id,
                    quantity=each,
                    unit=data.unit,
                    seed_lot_id=data.seed_lot_id,
                    notes=data.notes or (f"Siembra escalonada {i + 1} de {data.count}" if data.count > 1 else None),
                ),
            )
            for i in range(data.count)
        ]

    async def update_sowing(self, actor: Actor, sowing_id: UUID, data: SowingUpdate) -> SowingRead:
        _require_manager(actor)
        values = data.model_dump(exclude_unset=True)
        await self._check_refs(actor, values)
        sowing = await self.repo.update(PlanSowing, actor.account_id, sowing_id, values)
        if sowing is None:
            raise NotFoundError(f"Sowing {sowing_id} not found.")
        await self._sync_sowing_reminders(actor, sowing)
        return SowingRead.model_validate(sowing)

    async def _sync_sowing_reminders(self, actor: Actor, sowing: PlanSowing) -> None:
        reminders = await self.repo.list_reminders(actor.account_id, plan_id=sowing.plan_id, status="pendiente")
        for r in (r for r in reminders if r.sowing_id == sowing.id):
            if sowing.status != "pendiente":
                values = {"status": "hecho" if sowing.status == "sembrado" else "cancelado", "completed_at": utcnow()}
            else:
                values = {"due_at": self.at_local(sowing.sow_date)}
            await self.repo.update(Reminder, actor.account_id, r.id, values)

    async def delete_sowing(self, actor: Actor, sowing_id: UUID) -> None:
        _require_manager(actor)
        if not await self.repo.remove(PlanSowing, actor.account_id, sowing_id):
            raise NotFoundError(f"Sowing {sowing_id} not found.")

    async def sow(self, actor: Actor, sowing_id: UUID, data: SowRequest) -> SowingRead:
        """The planned sowing happened: start its crop cycle (with its stage reminders) and discount the seed."""
        _require_manager(actor)
        sowing = await self.repo.get(PlanSowing, actor.account_id, sowing_id)
        if sowing is None:
            raise NotFoundError(f"Sowing {sowing_id} not found.")
        if sowing.status == "sembrado":
            raise InvalidInputError("That sowing is already done.")
        plan = await self._plan(actor, sowing.plan_id)
        sown_on = data.sown_on or utcnow().astimezone(self.tz).date()
        values: dict = {"status": "sembrado", "sow_date": sown_on}
        if data.create_crop_cycle:
            field_id = plan.field_id
            if sowing.zone_id:
                field_id = (await self.farm.get_zone(actor, sowing.zone_id)).field_id
            if not field_id:
                raise InvalidInputError("The plan has no field: set one (or a zone on the sowing) to start the crop.")
            crop = await self.farm.get_crop_master(actor, sowing.crop_master_id)
            cycle = await self.farm.create_crop_cycle(
                actor,
                CropCycleCreate(
                    field_id=field_id,
                    crop_master_id=sowing.crop_master_id,
                    zone_id=sowing.zone_id,
                    status="planted",
                    planting_date=sown_on,
                    expected_harvest_date=sown_on + timedelta(days=crop.growth_period_days)
                    if crop.growth_period_days else None,
                    notes=f"Siembra del plan «{plan.name}»",
                ),
            )
            values["crop_cycle_id"] = cycle.id
        if data.consume_seed_lot and sowing.seed_lot_id and sowing.quantity:
            await self.inventory.consume_seed_lot(actor, sowing.seed_lot_id, sowing.quantity)
        updated = await self.repo.update(PlanSowing, actor.account_id, sowing_id, values)
        await self._sync_sowing_reminders(actor, updated)
        if updated.crop_cycle_id:
            await self.apply_cycle_plan(actor, updated.crop_cycle_id)
        return SowingRead.model_validate(updated)

    # ---------- crop cycle stage plan ----------

    async def propose_cycle_plan(self, actor: Actor, cycle_id: UUID) -> CyclePlanProposal:
        """Stages and reminders for a crop cycle from its crop's template: emergence, transplant, key
        milestones, "posible cosecha" and the expected harvest. Nothing is saved."""
        cycle = await self.farm.get_crop_cycle(actor, cycle_id)
        crop = await self.farm.get_crop_master(actor, cycle.crop_master_id)
        crop_name = f"{crop.name}{' ' + crop.variety if crop.variety else ''}"
        sowing = cycle.planting_date or utcnow().astimezone(self.tz).date()
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

        stages = [
            ProposedStage(
                name=name,
                stage=stage,
                start_date=start,
                end_date=points[i + 1][0] if i + 1 < len(points) else harvest,
            )
            for i, (start, stage, name, _) in enumerate(points)
        ]
        today = utcnow().astimezone(self.tz).date()
        reminders = [
            ProposedReminder(title=text, due_at=self.at_local(start), description=f"Etapa: {name}")
            for start, _, name, text in points
            if text and start >= today
        ]
        if harvest >= today:
            reminders.append(
                ProposedReminder(title=f"Cosecha estimada de {crop_name}", due_at=self.at_local(harvest))
            )
        return CyclePlanProposal(
            crop_cycle_id=cycle.id,
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
        cycle = await self.farm.get_crop_cycle(actor, cycle_id)
        existing = await self.repo.list_plans(actor.account_id, crop_cycle_id=cycle_id)
        if existing:
            plan = existing[0]
            await self.repo.clear_generated(plan.id)
        else:
            where = (await self.farm.get_zone(actor, cycle.zone_id)).label if cycle.zone_id else None
            plan = CropPlan(
                account_id=actor.account_id,
                field_id=cycle.field_id,
                zone_id=cycle.zone_id,
                crop_cycle_id=cycle.id,
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
                crop_cycle_id=cycle.id,
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
                    crop_cycle_id=cycle.id,
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
