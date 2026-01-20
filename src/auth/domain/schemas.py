# src/auth/domain/schemas.py
"""
Pydantic schemas for authentication.
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr
from uuid import UUID


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    first_name: str | None = None
    last_name: str | None = None


class UserCreate(UserBase):
    """Schema for creating a new user."""
    password: str
    account_id: UUID
    role: str | None = None


class UserRead(UserBase):
    """Schema for reading user data."""
    id: UUID
    account_id: UUID
    role: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Schema for login request."""
    email: str
    password: str


class TokenResponse(BaseModel):
    """Schema for token response."""
    access_token: str
    token_type: str = "bearer"
