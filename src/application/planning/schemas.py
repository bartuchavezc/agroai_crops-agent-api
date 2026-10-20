from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field as PField, model_validator

from src.application.farm.schemas import LotRead
from src.application.management.schemas import ORMModel, PartialUpdate
from src.application.tasks.schemas import TaskRead

PlanKind = Literal["ciclo", "largo"]
PlanStatus = Literal["borrador", "activo", "archivado"]
StageType = Literal[
    "germinacion", "plantin", "traspaso", "vegetativo", "floracion", "fructificacion", "cosecha",
    "establecimiento", "poda", "descanso", "otro",
]
ReminderStatus = Literal["activo", "pausado", "terminado"]
Recurrence = Literal["none", "daily", "weekly", "every_n_days"]
Source = Literal["user", "agent", "plan"]


def _check_recurrence(recurrence: Optional[str], interval_days: Optional[int]) -> None:
    if recurrence == "every_n_days" and not interval_days:
        raise ValueError("every_n_days needs interval_days.")


# ---------- Reminders ----------

class ReminderCreate(BaseModel):
    title: str = PField(min_length=1, max_length=255)
    due_at: datetime = PField(description="When to notify (without offset it is read as local time)")
    description: Optional[str] = None
    recurrence: Recurrence = "none"
    interval_days: Optional[int] = PField(default=None, ge=1, le=365)
    until: Optional[date] = None
    assigned_to: Optional[UUID] = PField(default=None, description="Only this member is notified (default: all)")
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _valid(self):
        _check_recurrence(self.recurrence, self.interval_days)
        return self


class ReminderUpdate(PartialUpdate):
    REQUIRED = ("title", "due_at", "recurrence", "status")

    title: Optional[str] = PField(default=None, min_length=1, max_length=255)
    due_at: Optional[datetime] = None
    description: Optional[str] = None
    recurrence: Optional[Recurrence] = None
    interval_days: Optional[int] = PField(default=None, ge=1, le=365)
    until: Optional[date] = None
    assigned_to: Optional[UUID] = None
    status: Optional[ReminderStatus] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None


class ReminderRead(ORMModel):
    id: UUID
    title: str
    description: Optional[str] = None
    due_at: datetime
    recurrence: Recurrence
    interval_days: Optional[int] = None
    until: Optional[date] = None
    assigned_to: Optional[UUID] = None
    status: ReminderStatus
    notified_at: Optional[datetime] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    source: Source
    created_at: datetime


# ---------- Plans ----------

class StageCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    stage: StageType = "otro"
    start_date: date
    end_date: Optional[date] = None
    crop_master_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    notes: Optional[str] = None
    remind: bool = PField(default=False, description="Also create a reminder on start_date")


class StageUpdate(PartialUpdate):
    REQUIRED = ("name", "stage", "start_date")

    name: Optional[str] = PField(default=None, min_length=1, max_length=255)
    stage: Optional[StageType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    zone_id: Optional[UUID] = None
    notes: Optional[str] = None


class StageRead(ORMModel):
    id: UUID
    plan_id: UUID
    name: str
    stage: StageType
    start_date: date
    end_date: Optional[date] = None
    position: int
    crop_master_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    notes: Optional[str] = None
    source: Source


PlanCropMode = Literal["single", "staggered", "perennial"]


class PlanCropCreate(BaseModel):
    """A crop the plan means to grow. single: one sowing on start_date; staggered: `count` sowings every
    `every_days` (lettuce every 15 days for continuous harvest); perennial: planted once to stay. Each sowing becomes
    a planned lot (in `zone_ids`, the plan's zones by default) with its "Sembrar" task."""
    crop_master_id: UUID
    mode: PlanCropMode = "single"
    start_date: date
    count: int = PField(default=1, ge=1, le=52)
    every_days: Optional[int] = PField(default=None, ge=1, le=365)
    quantity: Optional[float] = PField(default=None, gt=0, description="Per sowing")
    unit: Optional[str] = PField(default=None, max_length=30)
    zone_ids: list[UUID] = PField(default_factory=list)
    seed_lot_id: Optional[UUID] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "staggered":
            if self.count < 2 or not self.every_days:
                raise ValueError("A staggered crop needs count >= 2 and every_days.")
        else:
            self.count, self.every_days = 1, None
        return self


class PlanCropRead(ORMModel):
    id: UUID
    plan_id: UUID
    crop_master_id: UUID
    mode: PlanCropMode
    start_date: date
    count: int
    every_days: Optional[int] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    zone_ids: list[UUID] = []
    seed_lot_id: Optional[UUID] = None
    notes: Optional[str] = None


class LotSown(BaseModel):
    """A planned lot was sown: it is planted, its seed is discounted and its stage plan generated."""
    sown_on: Optional[date] = None
    consume_seed_lot: bool = True


class PlanCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    kind: PlanKind = "largo"
    status: PlanStatus = "activo"
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    zone_ids: list[UUID] = PField(default_factory=list, description="The zones a general plan covers")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    objectives: Optional[str] = None
    notes: Optional[str] = None
    stages: list[StageCreate] = PField(default_factory=list)
    crops: list[PlanCropCreate] = PField(default_factory=list)


class PlanUpdate(PartialUpdate):
    REQUIRED = ("name", "status")

    name: Optional[str] = PField(default=None, min_length=1, max_length=255)
    status: Optional[PlanStatus] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    zone_ids: Optional[list[UUID]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    objectives: Optional[str] = None
    notes: Optional[str] = None


class PlanRead(ORMModel):
    id: UUID
    name: str
    kind: PlanKind
    status: PlanStatus
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    zone_ids: list[UUID] = []
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    objectives: Optional[str] = None
    notes: Optional[str] = None
    source: Source
    created_at: datetime


class PlanDetail(PlanRead):
    stages: list[StageRead] = []
    crops: list[PlanCropRead] = []
    lots: list[LotRead] = []  # the lots it planned (or sowed)
    tasks: list[TaskRead] = []
    reminders: list[ReminderRead] = []


class ProposedStage(BaseModel):
    name: str
    stage: StageType
    start_date: date
    end_date: Optional[date] = None


class ProposedReminder(BaseModel):
    title: str
    due_at: datetime
    description: Optional[str] = None


class CyclePlanProposal(BaseModel):
    """Stage plan + reminders generated for a lot from its crop's template (preview or applied)."""
    lot_id: UUID
    crop_name: str
    sowing_date: date
    expected_harvest_date: Optional[date] = None
    stages: list[ProposedStage]
    reminders: list[ProposedReminder]
    plan_id: Optional[UUID] = None  # set once applied
