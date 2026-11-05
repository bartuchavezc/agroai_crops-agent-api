from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TodoStatus = Literal["pending", "in_progress", "done", "skipped"]


class Todo(BaseModel):
    id: str
    title: str = Field(max_length=160)
    status: TodoStatus = "pending"
    note: Optional[str] = Field(default=None, max_length=400)


class AgentTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: Optional[UUID] = None
    kind: str
    goal: str
    input: dict[str, Any] = {}
    status: str
    todos: list[Todo] = []
    trace: list[dict[str, Any]] = []
    result: Optional[str] = None
    error: Optional[str] = None
    max_calls: int
    used_calls: int
    tokens: int
    proposal_id: Optional[UUID] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime
