from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SupplyKind = Literal["phyto", "fertilizer", "amendment", "substrate", "biological", "other"]
MovementKind = Literal["receipt", "consumption", "adjustment"]


class SupplyItemCreate(BaseModel):
    """A product taken into stock, written as on its label. `quantity` is the first receipt."""
    kind: SupplyKind
    name: str = Field(min_length=1, max_length=255)
    registry_number: Optional[str] = Field(default=None, max_length=40)
    company: Optional[str] = Field(default=None, max_length=255)
    active_ingredients: Optional[str] = None
    formulation: Optional[str] = Field(default=None, max_length=60)
    unit: str = Field(description="l | ml | kg | g | unidad")
    quantity: float = Field(default=0, ge=0)
    manufacturer_lot: Optional[str] = Field(default=None, max_length=60)
    expiry_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None
    image_identifier: Optional[str] = Field(default=None, description="The remito or label photo of the receipt")


class SupplyItemUpdate(BaseModel):
    """Descriptive data only: the quantity changes through movements."""
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    registry_number: Optional[str] = Field(default=None, max_length=40)
    company: Optional[str] = Field(default=None, max_length=255)
    active_ingredients: Optional[str] = None
    formulation: Optional[str] = Field(default=None, max_length=60)
    manufacturer_lot: Optional[str] = Field(default=None, max_length=60)
    expiry_date: Optional[date] = None
    location: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = None


class SupplyItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: SupplyKind
    name: str
    registry_number: Optional[str] = None
    company: Optional[str] = None
    active_ingredients: Optional[str] = None
    formulation: Optional[str] = None
    registry_verified: bool
    unit: str
    quantity: float
    manufacturer_lot: Optional[str] = None
    expiry_date: Optional[date] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SupplyMovementCreate(BaseModel):
    """receipt: more came in (positive); adjustment: a correction after counting (signed), with its reason."""
    kind: Literal["receipt", "adjustment"]
    quantity: float
    unit: Optional[str] = Field(default=None, description="Default: the item's unit")
    reason: Optional[str] = None
    occurred_at: Optional[datetime] = None
    image_identifier: Optional[str] = None


class SupplyMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    kind: MovementKind
    quantity: float
    occurred_at: datetime
    reason: Optional[str] = None
    application_id: Optional[UUID] = None
    image_identifier: Optional[str] = None
    user_id: Optional[UUID] = None
    created_at: datetime
