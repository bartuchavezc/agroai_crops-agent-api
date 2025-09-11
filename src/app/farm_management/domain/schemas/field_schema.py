from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import datetime

class FieldBase(BaseModel):
    name: str = Field(..., max_length=255)
    account_id: UUID # Required on creation
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = Field(None, max_length=255)
    soil_type: Optional[str] = Field(None, max_length=255)

class FieldCreate(FieldBase):
    pass

class FieldUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    # account_id is typically not updatable as it defines ownership
    description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    city: Optional[str] = Field(None, max_length=255)
    soil_type: Optional[str] = Field(None, max_length=255)

class FieldRead(FieldBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True) 