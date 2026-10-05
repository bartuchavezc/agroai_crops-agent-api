"""
Planning module: crop plans (one crop cycle, or a long permaculture-style roadmap), their stages and
staggered sowings, and schedulable reminders that the `reminders` batch job turns into in-app
notifications when due. Same account / soft-delete pattern as management.
"""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

PLAN_KINDS = ("ciclo", "largo")  # one crop cycle | long roadmap (perennials, staggered sowings, seasons)
PLAN_STATUSES = ("borrador", "activo", "archivado")
STAGE_TYPES = (
    "germinacion", "plantin", "traspaso", "vegetativo", "floracion", "fructificacion", "cosecha",
    "establecimiento", "poda", "descanso", "otro",
)
SOWING_STATUSES = ("pendiente", "sembrado", "cancelado")
REMINDER_STATUSES = ("pendiente", "hecho", "cancelado")
RECURRENCES = ("none", "daily", "weekly", "every_n_days")
SOURCES = ("user", "agent", "plan")


class CropPlan(Base):
    __tablename__ = "crop_plans"
    __table_args__ = (
        CheckConstraint(f"kind IN {PLAN_KINDS}", name="plan_kind_valid"),
        CheckConstraint(f"status IN {PLAN_STATUSES}", name="plan_status_valid"),
        CheckConstraint(f"source IN {SOURCES}", name="plan_source_valid"),
        Index("ix_crop_plans_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"), index=True)
    name = Column(String(255), nullable=False)
    kind = Column(String(10), nullable=False, default="ciclo")
    status = Column(String(10), nullable=False, default="activo")
    start_date = Column(Date)
    end_date = Column(Date)
    notes = Column(Text)
    source = Column(String(10), nullable=False, default="user")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class PlanStage(Base):
    """A period of the plan: germinación, traspaso, floración... or, in a long plan, "poda invernal"."""
    __tablename__ = "plan_stages"
    __table_args__ = (CheckConstraint(f"stage IN {STAGE_TYPES}", name="stage_type_valid"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="SET NULL"))
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    stage = Column(String(20), nullable=False, default="otro")
    name = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    position = Column(Integer, nullable=False, default=0)
    notes = Column(Text)
    source = Column(String(10), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class PlanSowing(Base):
    """One planned sowing: which crop, where, which week and how much seed (staggered sowings split a lot
    over several weeks). Marking it sown can start the crop cycle and discount the seed lot."""
    __tablename__ = "plan_sowings"
    __table_args__ = (CheckConstraint(f"status IN {SOWING_STATUSES}", name="sowing_status_valid"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="RESTRICT"), nullable=False)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    sow_date = Column(Date, nullable=False)
    quantity = Column(Float)
    unit = Column(String(30))
    seed_lot_id = Column(UUID(as_uuid=True), ForeignKey("seed_lots.id", ondelete="SET NULL"))
    status = Column(String(10), nullable=False, default="pendiente")
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Reminder(Base):
    """Something to do at a given moment, optionally recurring. `due_at` is the current occurrence; the
    batch job notifies once per occurrence (`notified_at`) and moves a recurring one to its next occurrence."""
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(f"status IN {REMINDER_STATUSES}", name="reminder_status_valid"),
        CheckConstraint(f"recurrence IN {RECURRENCES}", name="reminder_recurrence_valid"),
        CheckConstraint(f"source IN {SOURCES}", name="reminder_source_valid"),
        Index("ix_reminders_account_due", "account_id", "due_at"),
        Index("ix_reminders_status_due", "status", "due_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), index=True)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("plan_stages.id", ondelete="SET NULL"))
    sowing_id = Column(UUID(as_uuid=True), ForeignKey("plan_sowings.id", ondelete="CASCADE"))
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"), index=True)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    due_at = Column(DateTime(timezone=True), nullable=False)
    recurrence = Column(String(15), nullable=False, default="none")
    interval_days = Column(Integer)
    until = Column(Date)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String(10), nullable=False, default="pendiente")
    notified_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    source = Column(String(10), nullable=False, default="user")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))
