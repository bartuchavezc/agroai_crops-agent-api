from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    field_id: Optional[UUID] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    archived: Optional[bool] = None
    field_id: Optional[UUID] = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: Optional[str] = None
    field_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant"]
    content: str
    image_identifier: Optional[str] = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["complete", "pending", "error"] = "complete"
    error_code: Optional[str] = None
    created_at: datetime
