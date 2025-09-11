from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from uuid import UUID
from datetime import date, datetime

class AccountBase(BaseModel):
    org_name: str = Field(..., max_length=255)
    plan: Optional[str] = Field(None, max_length=50)
    max_fields: Optional[int] = None
    subscription_start: Optional[date] = None

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    org_name: Optional[str] = Field(None, max_length=255)
    plan: Optional[str] = Field(None, max_length=50)
    max_fields: Optional[int] = None
    subscription_start: Optional[date] = None

class AccountRead(AccountBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True) 