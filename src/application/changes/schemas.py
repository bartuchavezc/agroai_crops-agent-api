from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

Entity = Literal["zone", "lot", "event", "seed_lot", "task", "reminder", "plan", "plan_crop", "stage"]
OpKind = Literal["create", "update", "delete"]


class Operation(BaseModel):
    """One write. `id`: the target of an update/delete. Any string "$N" (in `id` or inside `data`) stands for the id
    of what operation N (0-based) of the same set created: create a lot, then a task with `lot_id: "$0"`."""

    op: OpKind
    entity: Entity
    id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class ChangeSet(BaseModel):
    operations: list[Operation] = Field(min_length=1, max_length=200)
    excluded: list[int] = Field(default_factory=list, description="Indexes to skip")


class OperationPreview(BaseModel):
    index: int
    op: OpKind
    entity: Entity
    title: str
    before: Optional[dict[str, Any]] = None
    after: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class ChangeSetPreview(BaseModel):
    ok: bool
    items: list[OperationPreview]


class OperationResult(BaseModel):
    index: int
    op: OpKind
    entity: Entity
    ok: bool
    id: Optional[UUID] = None
    error: Optional[str] = None
    skipped: bool = False
    undone: bool = False


class ChangeSetResult(BaseModel):
    applied: int
    failed: int
    undone: bool = Field(False, description="An operation failed: what this set had created was removed again")
    items: list[OperationResult]


class ProposalRead(BaseModel):
    id: UUID
    title: str
    status: Literal["pending", "applied", "rejected", "failed"]
    conversation_id: Optional[UUID] = None
    operations: list[Operation]
    preview: list[OperationPreview]
    result: Optional[ChangeSetResult] = None
    created_at: datetime
    decided_at: Optional[datetime] = None


class ProposalDecision(BaseModel):
    excluded: list[int] = Field(default_factory=list, description="Indexes the user unticked")
