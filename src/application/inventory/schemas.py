from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField, field_validator

from .units import SEED_UNITS, normalize_tags, normalize_unit

SeedLotSort = Literal["expiry", "quantity", "recent", "name"]
AdjustOp = Literal["add", "subtract", "set"]


def _seed_unit(value: str) -> str:
    unit = normalize_unit(value)
    if unit is None:
        raise ValueError(f"unit must be one of {', '.join(SEED_UNITS)}")
    return unit


class SeedLotCreate(BaseModel):
    crop_master_id: UUID
    variety_note: Optional[str] = PField(default=None, max_length=255)
    quantity: float = PField(gt=0)
    unit: str = PField(default="semillas", max_length=30, description="semillas | gramos")
    thousand_seed_weight_g: Optional[float] = PField(default=None, gt=0, le=100000)
    tags: list[str] = PField(default_factory=list)
    acquired_date: Optional[date] = None
    expiry_date: Optional[date] = None
    source: Optional[str] = PField(default=None, max_length=255)
    notes: Optional[str] = None
    # When the same crop + variety already has a lot, add to it instead of creating another.
    merge_into_existing: bool = False

    check_unit = field_validator("unit")(_seed_unit)
    check_tags = field_validator("tags")(normalize_tags)


class SeedLotUpdate(BaseModel):
    """Only the fields sent are changed. Changing `unit` converts the quantity already on hand."""
    crop_master_id: Optional[UUID] = None
    variety_note: Optional[str] = PField(default=None, max_length=255)
    unit: Optional[str] = PField(default=None, max_length=30)
    thousand_seed_weight_g: Optional[float] = PField(default=None, gt=0, le=100000)
    tags: Optional[list[str]] = None
    acquired_date: Optional[date] = None
    expiry_date: Optional[date] = None
    source: Optional[str] = PField(default=None, max_length=255)
    notes: Optional[str] = None

    @field_validator("unit")
    @classmethod
    def check_unit(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _seed_unit(value)

    @field_validator("tags")
    @classmethod
    def check_tags(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return None if value is None else normalize_tags(value)


class SeedLotAdjust(BaseModel):
    """add / subtract / set (set 0 empties the lot), in seeds or grams: converted to the lot's unit."""
    op: AdjustOp
    amount: float = PField(ge=0)
    unit: Optional[str] = PField(default=None, description="semillas | gramos; defaults to the lot's unit")
    thousand_seed_weight_g: Optional[float] = PField(
        default=None, gt=0, le=100000, description="Saved on the lot, used for the conversion"
    )


class SeedLotMerge(BaseModel):
    target_id: UUID
    source_ids: list[UUID] = PField(min_length=1)


class SeedLotTagging(BaseModel):
    lot_ids: list[UUID] = PField(min_length=1)
    add: list[str] = PField(default_factory=list)
    remove: list[str] = PField(default_factory=list)

    check_add = field_validator("add")(normalize_tags)
    check_remove = field_validator("remove")(normalize_tags)


class SeedTagCount(BaseModel):
    tag: str
    count: int


class SeedLotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    crop_master_id: UUID
    variety_note: Optional[str] = None
    quantity: float
    unit: str
    thousand_seed_weight_g: Optional[float] = None
    tags: list[str] = PField(default_factory=list)
    acquired_date: Optional[date] = None
    expiry_date: Optional[date] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Derived from the lot and its crop.
    crop_name: Optional[str] = None
    crop_variety: Optional[str] = None
    crop_family: Optional[str] = None
    effective_thousand_seed_weight_g: Optional[float] = None
    equivalent_quantity: Optional[float] = None
    equivalent_unit: Optional[str] = None


class SeedLotAdjustResult(SeedLotRead):
    applied_amount: float = 0  # in the lot's unit, after conversion
    clamped: bool = False  # asked to subtract more than there was: the lot stays at 0


class SeedLotAddResult(SeedLotRead):
    merged: bool = False  # added to an existing lot of the same crop + variety
    duplicate_of: Optional[UUID] = None  # created apart although this lot has the same crop + variety
