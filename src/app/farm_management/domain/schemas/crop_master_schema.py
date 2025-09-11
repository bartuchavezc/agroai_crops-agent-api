from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class CropMasterBase(BaseModel):
    name: str = Field(..., max_length=255)
    variety: Optional[str] = Field(None, max_length=255)
    family: Optional[str] = Field(None, max_length=255)

class CropMasterCreate(CropMasterBase):
    pass

class CropMasterUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    variety: Optional[str] = Field(None, max_length=255)
    family: Optional[str] = Field(None, max_length=255)

class CropMasterRead(CropMasterBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 