from datetime import datetime
from pydantic import BaseModel, EmailStr
from uuid import UUID

class UserBase(BaseModel):
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None

class UserCreate(UserBase):
    password: str
    account_id: UUID
    role: str | None = None

class User(UserBase): # This is the Read schema
    id: UUID
    account_id: UUID
    role: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True 