from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ApplicationStatus = Literal["draft", "confirmed", "voided"]
ApplicationKind = Literal["phyto", "fertilization", "biological", "other"]
ProductKind = Literal["phyto", "fertilizer", "amendment", "substrate", "biological", "other"]
IntervalSource = Literal["label", "user", "saved", "none"]


class Evidence(BaseModel):
    kind: Literal["audio", "photo", "document"]
    identifier: str = Field(max_length=255)
    note: Optional[str] = None


class ApplicationProductIn(BaseModel):
    """A product as written on its label (or copied from the registry search). Interval days come from the label
    or the person; when omitted, an interval saved before for that product and crop is reused."""
    kind: ProductKind = "phyto"
    name: str = Field(min_length=1, max_length=255)
    registry_number: Optional[str] = Field(default=None, max_length=40)
    company: Optional[str] = Field(default=None, max_length=255)
    active_ingredients: Optional[str] = None
    formulation: Optional[str] = Field(default=None, max_length=60)
    dose: Optional[float] = Field(default=None, gt=0)
    dose_unit: Optional[str] = Field(default=None, max_length=30)
    total_quantity: Optional[float] = Field(default=None, gt=0)
    total_unit: Optional[str] = Field(default=None, max_length=10)
    supply_item_id: Optional[UUID] = Field(default=None, description="The stock item it was taken from")
    preharvest_interval_days: Optional[int] = Field(default=None, ge=0, le=365)
    reentry_interval_hours: Optional[int] = Field(default=None, ge=0, le=720)
    interval_source: Optional[Literal["label", "user"]] = Field(
        default=None, description="Where the interval days come from, when given"
    )


class ApplicationProductRead(ApplicationProductIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    registry_verified: bool
    interval_source: IntervalSource


class ApplicationBase(BaseModel):
    kind: ApplicationKind = "phyto"
    applied_at: Optional[datetime] = None
    target: Optional[str] = None
    followup_id: Optional[UUID] = Field(default=None, description="The follow-up (seguimiento) it treats, if any")
    method: Optional[str] = Field(default=None, max_length=60)
    equipment: Optional[str] = Field(default=None, max_length=255)
    area_m2: Optional[float] = Field(default=None, gt=0)
    water_volume_l: Optional[float] = Field(default=None, gt=0)
    operator_user_id: Optional[UUID] = None
    operator_name: Optional[str] = Field(default=None, max_length=255)
    prescribed_by: Optional[str] = Field(default=None, max_length=255)
    prescription_number: Optional[str] = Field(default=None, max_length=60)
    evidence: list[Evidence] = Field(default_factory=list)
    transcript: Optional[str] = None
    notes: Optional[str] = None


class ApplicationCreate(ApplicationBase):
    """A draft: nothing is in the record until it is confirmed. Where: lots, or a zone (every lot growing there),
    or neither (the whole field)."""
    field_id: UUID
    zone_id: Optional[UUID] = None
    lot_ids: list[UUID] = Field(default_factory=list)
    products: list[ApplicationProductIn] = Field(default_factory=list)


class ApplicationDraftUpdate(BaseModel):
    """Replaces what is given on a draft (products: the whole list)."""
    kind: Optional[ApplicationKind] = None
    applied_at: Optional[datetime] = None
    target: Optional[str] = None
    followup_id: Optional[UUID] = None
    method: Optional[str] = Field(default=None, max_length=60)
    equipment: Optional[str] = Field(default=None, max_length=255)
    area_m2: Optional[float] = Field(default=None, gt=0)
    water_volume_l: Optional[float] = Field(default=None, gt=0)
    operator_user_id: Optional[UUID] = None
    operator_name: Optional[str] = Field(default=None, max_length=255)
    prescribed_by: Optional[str] = Field(default=None, max_length=255)
    prescription_number: Optional[str] = Field(default=None, max_length=60)
    evidence: Optional[list[Evidence]] = None
    transcript: Optional[str] = None
    notes: Optional[str] = None
    zone_id: Optional[UUID] = None
    lot_ids: Optional[list[UUID]] = None
    products: Optional[list[ApplicationProductIn]] = None


class ApplicationCorrection(ApplicationDraftUpdate):
    """A new version of a confirmed record: what changes, and why."""
    reason: str = Field(min_length=3)


class ApplicationVoid(BaseModel):
    reason: str = Field(min_length=3)


class ApplicationFollowUpLink(BaseModel):
    """Which follow-up a record treats (null: none). Not part of the record's content, so no new version."""
    followup_id: Optional[UUID] = None


class ApplicationRead(ApplicationBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    record_id: UUID
    version: int
    is_current: bool
    supersedes_id: Optional[UUID] = None
    correction_reason: Optional[str] = None
    field_id: UUID
    zone_id: Optional[UUID] = None
    lot_ids: list[UUID] = Field(default_factory=list)
    status: ApplicationStatus
    harvest_release_date: Optional[date] = None
    reentry_until: Optional[datetime] = None
    weather: Optional[dict[str, Any]] = None
    source: str
    field_event_id: Optional[UUID] = None
    recorded_by: Optional[UUID] = None
    confirmed_by: Optional[UUID] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    products: list[ApplicationProductRead] = Field(default_factory=list)
    lot_labels: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, description="What a confirmed record still lacks")

    @model_validator(mode="before")
    @classmethod
    def _none_lists(cls, data):
        if isinstance(data, dict) and data.get("evidence") is None:
            data["evidence"] = []
        return data


class AccountProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ProductKind
    name: str
    registry_number: Optional[str] = None
    company: Optional[str] = None
    active_ingredients: Optional[str] = None
    formulation: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime


class ProductIntervalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_name: str
    crop_name: str
    preharvest_interval_days: Optional[int] = None
    reentry_interval_hours: Optional[int] = None
    source: str
    updated_at: datetime
