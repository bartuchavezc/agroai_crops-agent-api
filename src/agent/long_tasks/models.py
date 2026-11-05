"""Work the agent does in the background, outside a chat turn: planning several lots, re-planning one after an
observation, a longer job the person asked for. Like a coding harness: a visible to-do list, subagents with their own
context, a budget of model calls, a trace of what it did and why, and pauses for the person's approval."""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

TASK_KINDS = ("plan_lots", "replan_lot", "general")
TASK_STATUSES = ("queued", "running", "waiting_approval", "done", "failed", "cancelled")
OPEN_TASK_STATUSES = ("queued", "running", "waiting_approval")


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        CheckConstraint(f"kind IN {TASK_KINDS}", name="kind_valid"),
        CheckConstraint(f"status IN {TASK_STATUSES}", name="status_valid"),
        Index("ix_agent_tasks_status_created", "status", "created_at"),
        Index("ix_agent_tasks_account_created", "account_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # whose key
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    kind = Column(String(20), nullable=False)
    goal = Column(Text, nullable=False)
    input = Column(JSONB, nullable=False, default=dict)  # {lot_ids, reason, observation, replan}
    status = Column(String(20), nullable=False, default="queued")
    todos = Column(JSONB, nullable=False, default=list)  # [{id, title, status, note}]
    trace = Column(JSONB, nullable=False, default=list)  # [{at, kind, text}]
    result = Column(Text)
    error = Column(Text)
    max_calls = Column(Integer, nullable=False, default=60)  # model calls, subagents included
    used_calls = Column(Integer, nullable=False, default=0)
    tokens = Column(Integer, nullable=False, default=0)
    proposal_id = Column(UUID(as_uuid=True))  # what it waits on, in waiting_approval
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
