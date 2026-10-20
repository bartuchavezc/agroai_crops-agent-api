"""Tasks: one-off work with someone in charge and a state ("preparar sustrato para el Cantero 1", "trasplantar
los tomates"). Not reminders (those only notify, e.g. "regar") and not plans (the general intent)."""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.application.farm.models import EVENT_TYPES
from src.shared.database import Base
from src.shared.domain.base import utcnow

TASK_STATUSES = ("pendiente", "en_curso", "bloqueada", "hecha", "cancelada")
OPEN_TASK_STATUSES = ("pendiente", "en_curso", "bloqueada")
TASK_SOURCES = ("user", "agent", "plan")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(f"status IN {TASK_STATUSES}", name="status_valid"),
        CheckConstraint(f"source IN {TASK_SOURCES}", name="source_valid"),
        CheckConstraint(f"result_event_type IS NULL OR result_event_type IN {EVENT_TYPES}", name="result_type_valid"),
        Index("ix_tasks_account_status", "account_id", "status"),
        Index("ix_tasks_account_assigned", "account_id", "assigned_to"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"), index=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"), index=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="SET NULL"), index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    due_date = Column(Date)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String(20), nullable=False, default="pendiente")
    # What finishing it logs in the bitácora (a transplant, a soil preparation...), on its zone or lot.
    result_event_type = Column(String(30))
    completed_at = Column(DateTime(timezone=True))
    source = Column(String(10), nullable=False, default="user")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))
