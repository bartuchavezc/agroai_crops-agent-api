"""The application record (registro de aplicaciones): what was applied, where, how much, by whom, with what
withholding period — the cuaderno de campo that Good Agricultural Practices (BPA) ask for.

Auditable, not just structured:
- A record is a chain of versions (`record_id` is stable, `version` grows). A draft is edited in place: it isn't a
  record yet. Once confirmed it is never edited nor deleted: a correction is a new version that supersedes the
  previous one with its reason, a void is a last version saying so. `is_current` marks the version in force.
- Every product is copied as its formal text (brand, registry number, actives) at the time it was applied: the
  registry may change, what was applied must read the same years later. A product that isn't in the registry is
  written by hand and stays marked as not verified.
- Evidence (the audio it was dictated in, the label or remito photo) and the weather at the time are kept with it.
"""
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

APPLICATION_STATUSES = ("draft", "confirmed", "voided")
APPLICATION_KINDS = ("phyto", "fertilization", "biological", "other")
PRODUCT_KINDS = ("phyto", "fertilizer", "amendment", "substrate", "biological", "other")
INTERVAL_SOURCES = ("label", "user", "saved", "none")  # saved: reused from an earlier label for that crop


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint(f"status IN {APPLICATION_STATUSES}", name="status_valid"),
        CheckConstraint(f"kind IN {APPLICATION_KINDS}", name="kind_valid"),
        UniqueConstraint("record_id", "version", name="uq_applications_record_version"),
        Index("ix_applications_account_current", "account_id", "is_current", "applied_at"),
        Index("ix_applications_record", "record_id"),
        Index("ix_applications_lots", "lot_ids", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    version = Column(Integer, nullable=False, default=1)
    is_current = Column(Boolean, nullable=False, default=True)
    supersedes_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="RESTRICT"))
    correction_reason = Column(Text)

    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    zone_id = Column(UUID(as_uuid=True), ForeignKey("field_zones.id", ondelete="SET NULL"))
    lot_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default="{}")
    status = Column(String(10), nullable=False, default="draft")
    kind = Column(String(20), nullable=False, default="phyto")
    applied_at = Column(DateTime(timezone=True))
    target = Column(Text)  # the pest, disease or reason it was applied for
    # The problem being followed it treats ("pulgón en tomate"): its bitácora entry joins that follow-up's history.
    followup_id = Column(UUID(as_uuid=True), ForeignKey("followups.id", ondelete="SET NULL"))
    method = Column(String(60))  # mochila, pulverizadora, fertirriego, al voleo...
    equipment = Column(String(255))
    area_m2 = Column(Float)
    water_volume_l = Column(Float)  # caldo
    operator_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    operator_name = Column(String(255))  # who applied it, also when they have no user
    prescribed_by = Column(String(255))  # the asesor / ingeniero agrónomo who indicated it
    prescription_number = Column(String(60))  # receta agronómica, where required
    harvest_release_date = Column(Date)  # applied day + the longest preharvest interval of its products
    reentry_until = Column(DateTime(timezone=True))
    weather = Column(JSONB)  # conditions at that hour, from the weather data: {temperature_c, humidity_pct, ...}
    evidence = Column(JSONB, nullable=False, default=list, server_default="[]")  # [{kind, identifier, note}]
    transcript = Column(Text)  # what was dictated, when it came from an audio
    notes = Column(Text)
    source = Column(String(10), nullable=False, default="user")  # user | agent
    field_event_id = Column(UUID(as_uuid=True), ForeignKey("field_events.id", ondelete="SET NULL"))
    recorded_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ApplicationProduct(Base):
    __tablename__ = "application_products"
    __table_args__ = (
        CheckConstraint(f"kind IN {PRODUCT_KINDS}", name="kind_valid"),
        CheckConstraint(f"interval_source IN {INTERVAL_SOURCES}", name="interval_source_valid"),
        Index("ix_application_products_application", "application_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False, default=0)
    kind = Column(String(20), nullable=False, default="phyto")
    name = Column(String(255), nullable=False)
    registry_number = Column(String(40))
    company = Column(String(255))
    active_ingredients = Column(Text)
    formulation = Column(String(60))
    registry_verified = Column(Boolean, nullable=False, default=False)
    dose = Column(Float)
    dose_unit = Column(String(30))  # cc/L, ml/10 L, L/ha, g/m2...
    total_quantity = Column(Float)  # product used, for the stock
    total_unit = Column(String(10))
    supply_item_id = Column(UUID(as_uuid=True), ForeignKey("supply_items.id", ondelete="SET NULL"))
    preharvest_interval_days = Column(Integer)  # carencia
    reentry_interval_hours = Column(Integer)
    interval_source = Column(String(10), nullable=False, default="none")


class AccountProduct(Base):
    """A product the account used that the registry doesn't have (a homemade purín, an import, a brand too new):
    written once, offered again next time. Never mistaken for a registered one."""
    __tablename__ = "account_products"
    __table_args__ = (
        CheckConstraint(f"kind IN {PRODUCT_KINDS}", name="kind_valid"),
        UniqueConstraint("account_id", "name_norm", name="uq_account_products_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False, default="other")
    name = Column(String(255), nullable=False)
    name_norm = Column(String(255), nullable=False)
    registry_number = Column(String(40))
    company = Column(String(255))
    active_ingredients = Column(Text)
    formulation = Column(String(60))
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProductCropInterval(Base):
    """A product's withholding period for a crop as read on its label (or given by the person), kept so the next
    application of that product on that crop doesn't ask again. The agent never fills this from its own memory."""
    __tablename__ = "product_crop_intervals"
    __table_args__ = (
        UniqueConstraint("account_id", "product_norm", "crop_norm", name="uq_product_crop_intervals"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    product_norm = Column(String(255), nullable=False)
    crop_norm = Column(String(255), nullable=False)
    product_name = Column(String(255), nullable=False)
    crop_name = Column(String(255), nullable=False)
    preharvest_interval_days = Column(Integer)
    reentry_interval_hours = Column(Integer)
    source = Column(String(10), nullable=False)  # label | user
    updated_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
