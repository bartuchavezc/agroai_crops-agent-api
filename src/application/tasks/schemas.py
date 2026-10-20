from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField

from src.application.farm.schemas import EventType
from src.application.management.schemas import PartialUpdate

TaskStatus = Literal["pendiente", "en_curso", "bloqueada", "hecha", "cancelada"]
TaskSource = Literal["user", "agent", "plan"]


class TaskCreate(BaseModel):
    title: str = PField(min_length=1, max_length=255)
    description: Optional[str] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    due_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    status: TaskStatus = "pendiente"
    result_event_type: Optional[EventType] = PField(
        default=None, description="What finishing it logs in the bitácora (e.g. transplant), on its zone or lot"
    )


class TaskUpdate(PartialUpdate):
    REQUIRED = ("title", "status")

    title: Optional[str] = PField(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    due_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    status: Optional[TaskStatus] = None
    result_event_type: Optional[EventType] = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    due_date: Optional[date] = None
    assigned_to: Optional[UUID] = None
    status: TaskStatus
    result_event_type: Optional[EventType] = None
    completed_at: Optional[datetime] = None
    source: TaskSource = "user"
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
