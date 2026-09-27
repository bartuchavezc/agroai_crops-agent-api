from datetime import date, datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField

CropCycleStatus = Literal["planned", "planted", "growing", "harvested", "failed"]
EventType = Literal[
    "sowing",
    "transplant",
    "irrigation",
    "fertilization",
    "treatment",
    "pruning",
    "weeding",
    "pest_sighting",
    "disease_sighting",
    "harvest",
    "observation",
    "photo",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Fields ----------

class FieldBase(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    city: Optional[str] = None
    latitude: Optional[float] = PField(default=None, ge=-90, le=90)
    longitude: Optional[float] = PField(default=None, ge=-180, le=180)
    description: Optional[str] = None
    soil_type: Optional[str] = None
    area_m2: Optional[float] = PField(default=None, ge=0)


class FieldCreate(FieldBase):
    pass


class FieldUpdate(BaseModel):
    name: Optional[str] = PField(default=None, min_length=1, max_length=255)
    city: Optional[str] = None
    latitude: Optional[float] = PField(default=None, ge=-90, le=90)
    longitude: Optional[float] = PField(default=None, ge=-180, le=180)
    description: Optional[str] = None
    soil_type: Optional[str] = None
    area_m2: Optional[float] = PField(default=None, ge=0)


class FieldRead(FieldBase, ORMModel):
    id: UUID
    account_id: UUID
    created_at: datetime
    updated_at: datetime


# ---------- Crop masters ----------

class CropMasterBase(BaseModel):
    name: str = PField(min_length=1, max_length=255)
    variety: Optional[str] = None
    scientific_name: Optional[str] = None
    family: Optional[str] = None
    description: Optional[str] = None
    growth_period_days: Optional[int] = PField(default=None, ge=1, le=3650)
    planting_season: Optional[str] = None
    harvest_season: Optional[str] = None


class CropMasterCreate(CropMasterBase):
    pass


class CropMasterRead(CropMasterBase, ORMModel):
    id: UUID
    account_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    @property
    def is_global(self) -> bool:
        return self.account_id is None


# ---------- Crop cycles ----------

class CropCycleCreate(BaseModel):
    field_id: UUID
    crop_master_id: UUID
    planting_date: Optional[date] = None
    expected_harvest_date: Optional[date] = None
    actual_harvest_date: Optional[date] = None
    status: CropCycleStatus = "planned"
    notes: Optional[str] = None


class CropCycleUpdate(BaseModel):
    planting_date: Optional[date] = None
    expected_harvest_date: Optional[date] = None
    actual_harvest_date: Optional[date] = None
    status: Optional[CropCycleStatus] = None
    notes: Optional[str] = None


class CropCycleRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: UUID
    crop_master_id: UUID
    planting_date: Optional[date] = None
    expected_harvest_date: Optional[date] = None
    actual_harvest_date: Optional[date] = None
    status: CropCycleStatus
    notes: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


# ---------- Field events ----------

class FieldEventCreate(BaseModel):
    field_id: UUID
    crop_cycle_id: Optional[UUID] = None
    type: EventType
    occurred_at: Optional[datetime] = None
    quantity: Optional[float] = None
    unit: Optional[str] = PField(default=None, max_length=30)
    notes: Optional[str] = None
    data: Dict[str, Any] = PField(default_factory=dict)
    image_identifier: Optional[str] = None


class FieldEventUpdate(BaseModel):
    type: Optional[EventType] = None
    occurred_at: Optional[datetime] = None
    quantity: Optional[float] = None
    unit: Optional[str] = PField(default=None, max_length=30)
    notes: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class FieldEventRead(ORMModel):
    id: UUID
    account_id: UUID
    field_id: UUID
    crop_cycle_id: Optional[UUID] = None
    author_user_id: Optional[UUID] = None
    type: EventType
    occurred_at: datetime
    quantity: Optional[float] = None
    unit: Optional[str] = None
    notes: Optional[str] = None
    data: Dict[str, Any] = PField(default_factory=dict)
    image_identifier: Optional[str] = None
    source: Literal["user", "agent"]
    created_at: datetime


# ---------- Overview (used by the agent) ----------

class ActiveCycleSummary(BaseModel):
    id: UUID
    crop_name: str
    variety: Optional[str] = None
    status: CropCycleStatus
    planting_date: Optional[date] = None
    expected_harvest_date: Optional[date] = None


class FieldOverview(BaseModel):
    field: FieldRead
    active_cycles: list[ActiveCycleSummary]
    last_event_at: Optional[datetime] = None
