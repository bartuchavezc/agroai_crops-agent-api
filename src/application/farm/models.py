"""
Farm domain: fields (plots / garden beds), crop catalog, crop cycles and field events.
Everything hangs from an account; crop_masters with account_id NULL are the global catalog.
"""
import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

CROP_CYCLE_STATUSES = ("planned", "planted", "growing", "harvested", "failed")
ACTIVE_CROP_CYCLE_STATUSES = ("planned", "planted", "growing")
EVENT_TYPES = (
    "sowing",
    "transplant",
    "irrigation",
    "fertilization",
    "treatment",
    "pruning",
    "weeding",
    "pest_sighting",
    "disease_sighting",
    "harvest",
    "observation",
    "photo",
)
EVENT_SOURCES = ("user", "agent")


class Field(Base):
    __tablename__ = "fields"
    __table_args__ = (
        # Partial index: the name can be reused once the old field is soft-deleted.
        Index(
            "uq_fields_account_name_active",
            "account_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    city = Column(String(255))
    latitude = Column(Float)
    longitude = Column(Float)
    layout_view_bearing = Column(Float)  # compass bearing drawn upward on the plan; null = automatic
    boundary = Column(JSONB)  # list[[lat, lon], ...] — the field's own drawn boundary, not the ~500m zone
    description = Column(Text)
    soil_type = Column(String(100))
    area_m2 = Column(Float)
    length_m = Column(Float)
    width_m = Column(Float)
    layout_objects = Column(JSONB, nullable=False, default=list, server_default="[]")
    layout_photos = Column(JSONB, nullable=False, default=list, server_default="[]")
    soil_context = Column(JSONB)  # cached INTA soil lookup (src/application/soil_data); None until computed
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class CropMaster(Base):
    __tablename__ = "crop_masters"
    __table_args__ = (
        Index("ix_crop_masters_account_name", "account_id", "name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(255), nullable=False)
    variety = Column(String(255))
    scientific_name = Column(String(255))
    family = Column(String(255))
    description = Column(Text)
    growth_period_days = Column(Integer)
    planting_season = Column(String(255))
    harvest_season = Column(String(255))
    kc_initial = Column(Float)
    kc_mid = Column(Float)
    kc_late = Column(Float)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CropCycle(Base):
    __tablename__ = "crop_cycles"
    __table_args__ = (
        CheckConstraint(f"status IN {CROP_CYCLE_STATUSES}", name="status_valid"),
        Index("ix_crop_cycles_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False, index=True)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="RESTRICT"), nullable=False)
    planting_date = Column(Date)
    expected_harvest_date = Column(Date)
    actual_harvest_date = Column(Date)
    status = Column(String(20), nullable=False, default="planned")
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class FieldEvent(Base):
    __tablename__ = "field_events"
    __table_args__ = (
        CheckConstraint(f"type IN {EVENT_TYPES}", name="type_valid"),
        CheckConstraint(f"source IN {EVENT_SOURCES}", name="source_valid"),
        Index("ix_field_events_account_occurred", "account_id", "occurred_at"),
        Index("ix_field_events_field_occurred", "field_id", "occurred_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"))
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    type = Column(String(30), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    quantity = Column(Float)
    unit = Column(String(30))
    notes = Column(Text)
    data = Column(JSONB, nullable=False, default=dict)
    image_identifier = Column(String(255))
    source = Column(String(10), nullable=False, default="user")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
