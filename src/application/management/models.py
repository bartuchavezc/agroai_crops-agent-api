"""
Management module: shopping list, budget ledger, roadmap — the "organización, no IA" module from
future.md. Same account/Actor pattern as farm/inventory; not tied to a field (field_id optional).
"""
import uuid

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

SHOPPING_STATUSES = ("pendiente", "comprado")
BUDGET_TYPES = ("gasto", "ingreso")
ROADMAP_STATUSES = ("pendiente", "en_curso", "hecho")


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"
    __table_args__ = (
        CheckConstraint(f"status IN {SHOPPING_STATUSES}", name="shopping_status_valid"),
        Index("ix_shopping_list_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    name = Column(String(255), nullable=False)
    category = Column(String(100))
    quantity = Column(Float)
    unit = Column(String(30))
    estimated_price = Column(Float)
    status = Column(String(20), nullable=False, default="pendiente")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class BudgetEntry(Base):
    __tablename__ = "budget_entries"
    __table_args__ = (
        CheckConstraint(f"type IN {BUDGET_TYPES}", name="budget_type_valid"),
        Index("ix_budget_entries_account_date", "account_id", "date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("crop_cycles.id", ondelete="SET NULL"))
    description = Column(String(255), nullable=False)
    category = Column(String(100))
    amount = Column(Float, nullable=False)
    type = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))


class RoadmapItem(Base):
    __tablename__ = "roadmap_items"
    __table_args__ = (
        CheckConstraint(f"status IN {ROADMAP_STATUSES}", name="roadmap_status_valid"),
        Index("ix_roadmap_items_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="SET NULL"))
    title = Column(String(255), nullable=False)
    description = Column(Text)
    target_date = Column(Date)
    status = Column(String(20), nullable=False, default="pendiente")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))
