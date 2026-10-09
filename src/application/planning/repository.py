"""
Planning data access. Every query takes account_id, except `due_reminders` (the batch job, all accounts).
"""
from datetime import date, datetime
from typing import Optional, Sequence, Type, TypeVar, Union
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.application.farm.models import CropMaster

from .models import CropPlan, PlanSowing, PlanStage, Reminder, ReminderCompletion

Row = TypeVar("Row", CropPlan, PlanStage, PlanSowing, Reminder)

# Filter sentinel: "only rows where this column is NULL" (same convention as management).
NONE = "none"
IdFilter = Union[UUID, str, None]


def _soft(model) -> list:
    return [model.deleted_at.is_(None)] if hasattr(model, "deleted_at") else []


class PlanningRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    # ---------- generic ----------

    async def add(self, *rows: Row) -> None:
        async with self.session_factory() as session:
            session.add_all(rows)
            await session.commit()
            for row in rows:
                await session.refresh(row)

    async def get(self, model: Type[Row], account_id: UUID, row_id: UUID) -> Optional[Row]:
        async with self.session_factory() as session:
            return (
                await session.execute(
                    select(model).where(model.id == row_id, model.account_id == account_id, *_soft(model))
                )
            ).scalar_one_or_none()

    async def update(self, model: Type[Row], account_id: UUID, row_id: UUID, values: dict) -> Optional[Row]:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(model).where(model.id == row_id, model.account_id == account_id, *_soft(model))
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
        return row

    async def remove(self, model: Type[Row], account_id: UUID, row_id: UUID) -> bool:
        """Soft delete for plans/reminders, hard delete for stages/sowings (their reminders cascade)."""
        async with self.session_factory() as session:
            if hasattr(model, "deleted_at"):
                stmt = (
                    update(model)
                    .where(model.id == row_id, model.account_id == account_id, model.deleted_at.is_(None))
                    .values(deleted_at=func.now())
                )
            else:
                stmt = delete(model).where(model.id == row_id, model.account_id == account_id)
            result = await session.execute(stmt)
            await session.commit()
        return result.rowcount > 0

    # ---------- plans ----------

    async def list_plans(
        self,
        account_id: UUID,
        field_id: Optional[UUID] = None,
        status: Optional[str] = None,
        crop_cycle_id: Optional[UUID] = None,
    ) -> Sequence[CropPlan]:
        stmt = select(CropPlan).where(CropPlan.account_id == account_id, CropPlan.deleted_at.is_(None))
        if field_id:
            stmt = stmt.where(CropPlan.field_id == field_id)
        if status:
            stmt = stmt.where(CropPlan.status == status)
        if crop_cycle_id:
            stmt = stmt.where(CropPlan.crop_cycle_id == crop_cycle_id)
        stmt = stmt.order_by(CropPlan.start_date.desc().nulls_last(), CropPlan.created_at.desc())
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def plan_children(
        self, plan_id: UUID
    ) -> tuple[Sequence[PlanStage], Sequence[PlanSowing], Sequence[Reminder]]:
        async with self.session_factory() as session:
            stages = (
                await session.execute(
                    select(PlanStage)
                    .where(PlanStage.plan_id == plan_id)
                    .order_by(PlanStage.start_date, PlanStage.position)
                )
            ).scalars().all()
            sowings = (
                await session.execute(
                    select(PlanSowing).where(PlanSowing.plan_id == plan_id).order_by(PlanSowing.sow_date)
                )
            ).scalars().all()
            reminders = (
                await session.execute(
                    select(Reminder)
                    .where(Reminder.plan_id == plan_id, Reminder.deleted_at.is_(None))
                    .order_by(Reminder.due_at)
                )
            ).scalars().all()
        return stages, sowings, reminders

    async def clear_generated(self, plan_id: UUID) -> None:
        """Drop what a template generated for a plan (stages, and reminders not yet done), before regenerating."""
        async with self.session_factory() as session:
            await session.execute(
                delete(Reminder).where(
                    Reminder.plan_id == plan_id, Reminder.source == "plan", Reminder.status == "pendiente"
                )
            )
            await session.execute(delete(PlanStage).where(PlanStage.plan_id == plan_id, PlanStage.source == "plan"))
            await session.commit()

    async def cancel_plan_reminders(self, account_id: UUID, plan_id: UUID) -> None:
        async with self.session_factory() as session:
            await session.execute(
                update(Reminder)
                .where(Reminder.account_id == account_id, Reminder.plan_id == plan_id, Reminder.status == "pendiente")
                .values(status="cancelado")
            )
            await session.commit()

    # ---------- reminders ----------

    async def list_reminders(
        self,
        account_id: UUID,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        field_id: Optional[UUID] = None,
        crop_cycle_id: Optional[UUID] = None,
        plan_id: Optional[UUID] = None,
        assigned_to: IdFilter = None,
        limit: int = 200,
        zone_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
    ) -> Sequence[Reminder]:
        stmt = select(Reminder).where(Reminder.account_id == account_id, Reminder.deleted_at.is_(None))
        if zone_id:
            stmt = stmt.where(Reminder.zone_id == zone_id)
        if before:  # history: only those due before the oldest one already received
            stmt = stmt.where(Reminder.due_at < before)
        if status:
            stmt = stmt.where(Reminder.status == status)
        if since:
            stmt = stmt.where(Reminder.due_at >= since)
        if until:
            stmt = stmt.where(Reminder.due_at < until)
        if field_id:
            stmt = stmt.where(Reminder.field_id == field_id)
        if crop_cycle_id:
            stmt = stmt.where(Reminder.crop_cycle_id == crop_cycle_id)
        if plan_id:
            stmt = stmt.where(Reminder.plan_id == plan_id)
        if assigned_to == NONE:
            stmt = stmt.where(Reminder.assigned_to.is_(None))
        elif assigned_to:
            # "mine": assigned to me, or to nobody (everyone gets those).
            stmt = stmt.where(or_(Reminder.assigned_to == assigned_to, Reminder.assigned_to.is_(None)))
        stmt = stmt.order_by(Reminder.due_at.desc() if before else Reminder.due_at, Reminder.id).limit(limit)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def due_reminders(self, now: datetime, limit: int = 500) -> Sequence[Reminder]:
        """Pending reminders whose current occurrence is due and wasn't notified yet (all accounts)."""
        stmt = (
            select(Reminder)
            .where(
                Reminder.deleted_at.is_(None),
                Reminder.status == "pendiente",
                Reminder.due_at <= now,
                or_(Reminder.notified_at.is_(None), Reminder.notified_at < Reminder.due_at),
            )
            .order_by(Reminder.due_at)
            .limit(limit)
        )
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def completions(
        self, account_id: UUID, zone_id: Optional[UUID] = None, before: Optional[datetime] = None, limit: int = 50
    ) -> Sequence[ReminderCompletion]:
        stmt = select(ReminderCompletion).where(ReminderCompletion.account_id == account_id)
        if zone_id:
            stmt = stmt.where(ReminderCompletion.zone_id == zone_id)
        if before:
            stmt = stmt.where(ReminderCompletion.completed_at < before)
        stmt = stmt.order_by(ReminderCompletion.completed_at.desc(), ReminderCompletion.id.desc()).limit(limit)
        async with self.session_factory() as session:
            return (await session.execute(stmt)).scalars().all()

    async def calendar_rows(
        self, account_id: UUID, since: date, until: date, since_dt: datetime, until_dt: datetime,
        field_id: Optional[UUID] = None,
    ) -> tuple[list[tuple[PlanStage, CropPlan]], list[tuple[PlanSowing, CropPlan, CropMaster]], list[Reminder]]:
        """What falls in [since, until] (dates, inclusive) / [since_dt, until_dt) (instants): the stages of active
        plans, the planned or done sowings, and the pending reminders (recurring ones from before the window too:
        they repeat into it). Reminders already represented by a stage or a sowing are left out."""
        plan_ok = (CropPlan.account_id == account_id, CropPlan.deleted_at.is_(None), CropPlan.status == "activo")
        if field_id:
            plan_ok = (*plan_ok, CropPlan.field_id == field_id)
        async with self.session_factory() as session:
            stages = (await session.execute(
                select(PlanStage, CropPlan).join(CropPlan, CropPlan.id == PlanStage.plan_id).where(
                    *plan_ok, PlanStage.start_date <= until,
                    func.coalesce(PlanStage.end_date, PlanStage.start_date) >= since,
                ).order_by(PlanStage.start_date, PlanStage.position)
            )).all()
            sowings = (await session.execute(
                select(PlanSowing, CropPlan, CropMaster)
                .join(CropPlan, CropPlan.id == PlanSowing.plan_id)
                .join(CropMaster, CropMaster.id == PlanSowing.crop_master_id)
                .where(*plan_ok, PlanSowing.status.in_(("pendiente", "sembrado")), PlanSowing.sow_date >= since,
                       PlanSowing.sow_date <= until)
                .order_by(PlanSowing.sow_date)
            )).all()
            remind = select(Reminder).where(
                Reminder.account_id == account_id, Reminder.deleted_at.is_(None), Reminder.status == "pendiente",
                Reminder.stage_id.is_(None), Reminder.sowing_id.is_(None), Reminder.due_at < until_dt,
                or_(Reminder.recurrence != "none", Reminder.due_at >= since_dt),
                or_(Reminder.until.is_(None), Reminder.until >= since),
            )
            if field_id:
                remind = remind.where(Reminder.field_id == field_id)
            reminders = (await session.execute(remind.order_by(Reminder.due_at))).scalars().all()
        return [(a, b) for a, b in stages], [(a, b, c) for a, b, c in sowings], list(reminders)
