import datetime as dt
from datetime import date, datetime
from typing import ClassVar, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField, model_validator

ShoppingStatus = Literal["pendiente", "comprado", "cancelado"]
BudgetType = Literal["gasto", "ingreso"]
RoadmapStatus = Literal["pendiente", "en_curso", "hecho", "cancelado"]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PartialUpdate(BaseModel):
    """PUT bodies are partial: only the keys sent are applied, and an explicit null clears an optional
    value (field_id, assigned_to, category...). Keys listed in REQUIRED can't be cleared."""
    REQUIRED: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _required_not_null(self):
        for key in self.REQUIRED:
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} can't be null.")
        return self


# ---------- Shopping list ----------

class ShoppingItemCreate(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    category: Optional[str] = PField(default=None, max_length=100)
    quantity: Optional[float] = PField(default=None, ge=0)
    unit: Optional[str] = PField(default=None, max_length=30)
    estimated_price: Optional[float] = PField(default=None, ge=0)


class ShoppingItemUpdate(PartialUpdate):
    REQUIRED = ("name", "status")

    name: Optional[str] = PField(default=None, min_length=1, max_length=255)
    status: Optional[ShoppingStatus] = None
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    category: Optional[str] = PField(default=None, max_length=100)
    quantity: Optional[float] = PField(default=None, ge=0)
    unit: Optional[str] = PField(default=None, max_length=30)
    estimated_price: Optional[float] = PField(default=None, ge=0)


class ShoppingItemRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
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
    category: Optional[str] = PField(default=None, max_length=100)
    currency: Optional[str] = PField(
        default=None, pattern=r"^[A-Z]{3}$", description="ISO-4217; omit for the account's"
    )


class BudgetEntryUpdate(PartialUpdate):
    REQUIRED = ("description", "amount", "type", "date")

    description: Optional[str] = PField(default=None, min_length=1, max_length=255)
    amount: Optional[float] = PField(default=None, gt=0)
    type: Optional[BudgetType] = None
    date: Optional[dt.date] = None
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    category: Optional[str] = PField(default=None, max_length=100)
    currency: Optional[str] = PField(
        default=None, pattern=r"^[A-Z]{3}$", description="ISO-4217; omit for the account's"
    )


class BudgetEntryRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    description: str
    category: Optional[str] = None
    currency: Optional[str] = None
    amount: float
    type: BudgetType
    date: date
    created_at: datetime


class BudgetSummary(BaseModel):
    period: str
    field_id: Optional[UUID] = None
    total_gastos: float
    total_ingresos: float
    balance: float
    by_category: dict[str, float]
    currency: Optional[str] = None  # the currency of the totals above (the account's)
    other_currencies: dict[str, float] = PField(
        default_factory=dict, description="Net balance of entries in other currencies"
    )
    # Only with `cycle_id`: how the cycle's cost compares with what it is expected to yield.
    cycle_id: Optional[UUID] = None
    crop_master_id: Optional[UUID] = None
    cost_per_plant: Optional[float] = None
    break_even_kg: Optional[float] = None
    expected_revenue: Optional[float] = None
    margin: Optional[float] = None


class BudgetCategory(BaseModel):
    key: str
    label: str
    type: BudgetType


# ---------- Roadmap ----------

class RoadmapItemCreate(BaseModel):
    title: str = PField(min_length=1, max_length=255)
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    description: Optional[str] = None
    target_date: Optional[date] = None


class RoadmapItemUpdate(PartialUpdate):
    REQUIRED = ("title", "status")

    status: Optional[RoadmapStatus] = None
    title: Optional[str] = PField(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    target_date: Optional[date] = None
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None


class RoadmapItemRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    assigned_to: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    target_date: Optional[date] = None
    status: RoadmapStatus
    created_at: datetime
