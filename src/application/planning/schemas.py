from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field as PField, model_validator

from src.application.management.schemas import ORMModel, PartialUpdate

PlanKind = Literal["ciclo", "largo"]
PlanStatus = Literal["borrador", "activo", "archivado"]
StageType = Literal[
    "germinacion", "plantin", "traspaso", "vegetativo", "floracion", "fructificacion", "cosecha",
    "establecimiento", "poda", "descanso", "otro",
]
SowingStatus = Literal["pendiente", "sembrado", "cancelado"]
ReminderStatus = Literal["pendiente", "hecho", "cancelado"]
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
    crop_cycle_id: Optional[UUID] = None
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
    crop_cycle_id: Optional[UUID] = None


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
    completed_at: Optional[datetime] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    stage_id: Optional[UUID] = None
    sowing_id: Optional[UUID] = None
    source: Source
    created_at: datetime


# ---------- Plans ----------

class StageCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    stage: StageType = "otro"
    start_date: date
    end_date: Optional[date] = None
    crop_master_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
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
    crop_cycle_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    notes: Optional[str] = None
    source: Source


class SowingCreate(BaseModel):
    crop_master_id: UUID
    sow_date: date
    zone_id: Optional[UUID] = None
    quantity: Optional[float] = PField(default=None, gt=0)
    unit: Optional[str] = PField(default=None, max_length=30)
    seed_lot_id: Optional[UUID] = None
    notes: Optional[str] = None


class StaggeredSowingCreate(BaseModel):
    """Split a sowing over time: `count` sowings every `every_days` from `start_date`, dividing
    total_quantity evenly (e.g. 300 lettuce seeds in 6 sowings, one every 15 days)."""
    crop_master_id: UUID
    start_date: date
    count: int = PField(ge=1, le=52)
    every_days: int = PField(ge=1, le=180)
    zone_id: Optional[UUID] = None
    total_quantity: Optional[float] = PField(default=None, gt=0)
    unit: Optional[str] = PField(default=None, max_length=30)
    seed_lot_id: Optional[UUID] = None
    notes: Optional[str] = None


class SowingUpdate(PartialUpdate):
    REQUIRED = ("sow_date", "status")

    sow_date: Optional[date] = None
    zone_id: Optional[UUID] = None
    quantity: Optional[float] = PField(default=None, gt=0)
    unit: Optional[str] = PField(default=None, max_length=30)
    seed_lot_id: Optional[UUID] = None
    status: Optional[SowingStatus] = None
    notes: Optional[str] = None


class SowingRead(ORMModel):
    id: UUID
    plan_id: UUID
    crop_master_id: UUID
    zone_id: Optional[UUID] = None
    sow_date: date
    quantity: Optional[float] = None
    unit: Optional[str] = None
    seed_lot_id: Optional[UUID] = None
    status: SowingStatus
    crop_cycle_id: Optional[UUID] = None
    notes: Optional[str] = None


class SowRequest(BaseModel):
    """Mark a planned sowing as done: optionally start its crop cycle and discount the seed lot."""
    sown_on: Optional[date] = None
    create_crop_cycle: bool = True
    consume_seed_lot: bool = True


class PlanCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    kind: PlanKind = "largo"
    status: PlanStatus = "activo"
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    stages: list[StageCreate] = PField(default_factory=list)
    sowings: list[SowingCreate] = PField(default_factory=list)


class PlanUpdate(PartialUpdate):
    REQUIRED = ("name", "status")

    name: Optional[str] = PField(default=None, min_length=1, max_length=255)
    status: Optional[PlanStatus] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class PlanRead(ORMModel):
    id: UUID
    name: str
    kind: PlanKind
    status: PlanStatus
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    source: Source
    created_at: datetime


class PlanDetail(PlanRead):
    stages: list[StageRead] = []
    sowings: list[SowingRead] = []
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
    """Stage plan + reminders generated for a crop cycle from its crop's template (preview or applied)."""
    crop_cycle_id: UUID
    crop_name: str
    sowing_date: date
    expected_harvest_date: Optional[date] = None
    stages: list[ProposedStage]
    reminders: list[ProposedReminder]
    plan_id: Optional[UUID] = None  # set once applied
