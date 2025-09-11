from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime

class CropCycleBase(BaseModel):
    field_id: UUID
    crop_master_id: UUID
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None

class CropCycleCreate(CropCycleBase):
    pass

class CropCycleUpdate(BaseModel):
    # field_id and crop_master_id are usually not updatable directly on a cycle
    # It might be better to end a cycle and start a new one if these change.
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None

class CropCycleRead(CropCycleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 