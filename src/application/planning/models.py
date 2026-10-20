"""
Planning module: crop plans — a lot's stage plan, or a general plan ("Plan Cantero 1: hoja y raíz fina", "Plan
alimentación anual") with objectives, zones and the crops it means to grow (once, staggered or perennial), which
become planned lots with their sowing tasks — plus stages, and schedulable reminders that the `reminders` batch job
turns into in-app notifications when due. Same account / soft-delete pattern as management.
"""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

PLAN_KINDS = ("ciclo", "largo")  # one lot's stage plan | a general plan (objectives, zones, crops over time)
PLAN_STATUSES = ("borrador", "activo", "archivado")
STAGE_TYPES = (
    "germinacion", "plantin", "traspaso", "vegetativo", "floracion", "fructificacion", "cosecha",
    "establecimiento", "poda", "descanso", "otro",
)
# How a crop of a plan is sown: once, several times every N days (continuous harvest), or once to stay (perennial).
PLAN_CROP_MODES = ("single", "staggered", "perennial")
# A reminder only notifies (it is never "done"): activo sends its occurrences, pausado holds them, terminado is a
# one-off already sent or a series past its end.
REMINDER_STATUSES = ("activo", "pausado", "terminado")
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
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"), index=True)
    name = Column(String(255), nullable=False)
    kind = Column(String(10), nullable=False, default="ciclo")
    status = Column(String(10), nullable=False, default="activo")
    start_date = Column(Date)
    end_date = Column(Date)
    objectives = Column(Text)  # what the plan is for: "hoja y raíz fina todo el año", "alimentación variada"
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
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"))
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


class PlanZone(Base):
    """The zones a general plan covers."""
    __tablename__ = "plan_zones"

    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), primary_key=True)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="CASCADE"), primary_key=True)


class PlanCrop(Base):
    """A crop the plan means to grow: once, staggered (`count` sowings every `every_days`, e.g. lettuce every 15
    days for continuous harvest) or perennial. Each sowing becomes a planned lot with its sowing task; doing the
    task (or marking the lot sown) plants the lot and discounts the seed lot."""
    __tablename__ = "plan_crops"
    __table_args__ = (CheckConstraint(f"mode IN {PLAN_CROP_MODES}", name="mode_valid"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="RESTRICT"), nullable=False)
    mode = Column(String(10), nullable=False, default="single")
    start_date = Column(Date, nullable=False)
    every_days = Column(Integer)
    count = Column(Integer, nullable=False, default=1)
    quantity = Column(Float)  # per sowing
    unit = Column(String(30))
    zone_ids = Column(JSONB, nullable=False, default=list, server_default="[]")
    seed_lot_id = Column(UUID(as_uuid=True), ForeignKey("seed_lots.id", ondelete="SET NULL"))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class Reminder(Base):
    """A notice at a given moment, optionally recurring ("regar el cantero 2", "si llueve no regar"). `due_at` is
    the current occurrence; the batch job notifies once per occurrence (`notified_at`) and moves a recurring one to
    its next occurrence. It is never completed: what shows is the notification, dismissed like any other."""
    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(f"status IN {REMINDER_STATUSES}", name="reminder_status_valid"),
        CheckConstraint(f"recurrence IN {RECURRENCES}", name="reminder_recurrence_valid"),
        CheckConstraint(f"source IN {SOURCES}", name="reminder_source_valid"),
        Index("ix_reminders_account_due", "account_id", "due_at"),
        Index("ix_reminders_zone_due", "zone_id", "due_at"),
        Index("ix_reminders_status_due", "status", "due_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("crop_plans.id", ondelete="CASCADE"), index=True)
    stage_id = Column(UUID(as_uuid=True), ForeignKey("plan_stages.id", ondelete="SET NULL"))
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="SET NULL"), index=True)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    due_at = Column(DateTime(timezone=True), nullable=False)
    recurrence = Column(String(15), nullable=False, default="none")
    interval_days = Column(Integer)
    until = Column(Date)
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    status = Column(String(10), nullable=False, default="activo")
    notified_at = Column(DateTime(timezone=True))
    source = Column(String(10), nullable=False, default="user")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))

