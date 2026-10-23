"""Inputs in stock besides seeds (phytosanitaries, fertilizers, amendments, substrates...) and the ledger of what
came in and went out. The product is kept as its formal text (brand, registry number, actives), never as a pointer
to the registry: what was bought is what it said on the label that day, registered or not.

The ledger is append-only: a mistake is fixed by another movement (an adjustment with its reason), and the item's
quantity is always the sum of its movements."""
import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

SUPPLY_KINDS = ("phyto", "fertilizer", "amendment", "substrate", "biological", "other")
MOVEMENT_KINDS = ("receipt", "consumption", "adjustment")


class SupplyItem(Base):
    __tablename__ = "supply_items"
    __table_args__ = (
        CheckConstraint(f"kind IN {SUPPLY_KINDS}", name="kind_valid"),
        Index("ix_supply_items_account", "account_id", "deleted_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False)
    name = Column(String(255), nullable=False)  # brand / commercial name as on the label
    registry_number = Column(String(40))  # SENASA (or the country's) number, as text
    company = Column(String(255))
    active_ingredients = Column(Text)  # "Clorpirifós 48% p/v", as written in the registry or the label
    formulation = Column(String(60))
    registry_verified = Column(Boolean, nullable=False, default=False)  # matched a registry row when added
    unit = Column(String(10), nullable=False)  # l | ml | kg | g | unidad
    quantity = Column(Float, nullable=False, default=0.0)  # sum of the ledger
    manufacturer_lot = Column(String(60))
    expiry_date = Column(Date)
    location = Column(String(255))
    notes = Column(Text)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class SupplyMovement(Base):
    __tablename__ = "supply_movements"
    __table_args__ = (
        CheckConstraint(f"kind IN {MOVEMENT_KINDS}", name="kind_valid"),
        Index("ix_supply_movements_item", "item_id", "occurred_at"),
        Index("ix_supply_movements_application", "application_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("supply_items.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(20), nullable=False)
    quantity = Column(Float, nullable=False)  # signed, in the item's unit: + in, - out
    occurred_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    reason = Column(Text)
    application_id = Column(UUID(as_uuid=True))  # the application version that consumed it (no FK: versions stay)
    image_identifier = Column(String(255))  # the remito / label photo
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
