"""Seed inventory: what's actually on hand, so crop-cycle creation can draw from real stock."""
import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow


class SeedLot(Base):
    __tablename__ = "seed_lots"
    __table_args__ = (Index("ix_seed_lots_account", "account_id", "deleted_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("crop_masters.id", ondelete="RESTRICT"), nullable=False)
    variety_note = Column(String(255))
    variety_i18n = Column(JSONB, nullable=False, default=dict, server_default="{}")  # {"es-MX": "..."}
    quantity = Column(Float, nullable=False)
    unit = Column(String(30), nullable=False, default="semillas")
    acquired_date = Column(Date)
    expiry_date = Column(Date)
    source = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime(timezone=True))
