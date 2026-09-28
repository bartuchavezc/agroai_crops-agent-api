from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField

ShoppingStatus = Literal["pendiente", "comprado"]
BudgetType = Literal["gasto", "ingreso"]
RoadmapStatus = Literal["pendiente", "en_curso", "hecho"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Shopping list ----------

class ShoppingItemCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    field_id: Optional[UUID] = None
    category: Optional[str] = None
    quantity: Optional[float] = PField(default=None, ge=0)
    unit: Optional[str] = None
    estimated_price: Optional[float] = PField(default=None, ge=0)


class ShoppingItemUpdate(BaseModel):
    status: Optional[ShoppingStatus] = None
    quantity: Optional[float] = PField(default=None, ge=0)
    estimated_price: Optional[float] = PField(default=None, ge=0)


class ShoppingItemRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    name: str
    category: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    estimated_price: Optional[float] = None
    status: ShoppingStatus
    created_at: datetime


# ---------- Budget ----------

class BudgetEntryCreate(BaseModel):
    description: str = PField(min_length=1, max_length=255)
    amount: float = PField(gt=0)
    type: BudgetType
    date: date
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    category: Optional[str] = None


class BudgetEntryRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    description: str
    category: Optional[str] = None
    amount: float
    type: BudgetType
    date: date
    created_at: datetime


class BudgetSummary(BaseModel):
    period: str
    total_gastos: float
    total_ingresos: float
    balance: float
    by_category: dict[str, float]


# ---------- Roadmap ----------

class RoadmapItemCreate(BaseModel):
    title: str = PField(min_length=1, max_length=255)
    field_id: Optional[UUID] = None
    description: Optional[str] = None
    target_date: Optional[date] = None


class RoadmapItemUpdate(BaseModel):
    status: Optional[RoadmapStatus] = None
    title: Optional[str] = PField(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    target_date: Optional[date] = None


class RoadmapItemRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    target_date: Optional[date] = None
    status: RoadmapStatus
    created_at: datetime
