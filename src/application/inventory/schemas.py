from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field as PField


class SeedLotCreate(BaseModel):
    crop_master_id: UUID
    variety_note: Optional[str] = None
    quantity: float = PField(gt=0)
    unit: str = PField(default="semillas", max_length=30)
    acquired_date: Optional[date] = None
    expiry_date: Optional[date] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class SeedLotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    crop_master_id: UUID
    variety_note: Optional[str] = None
    quantity: float
    unit: str
    acquired_date: Optional[date] = None
    expiry_date: Optional[date] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
