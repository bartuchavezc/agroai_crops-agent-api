import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

SEVERITIES = ("low", "medium", "high", "critical")
ALERT_SOURCES = ("rule", "smn", "agent", "user")


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint(f"severity IN {SEVERITIES}", name="severity_valid"),
        CheckConstraint(f"source IN {ALERT_SOURCES}", name="source_valid"),
        Index("ix_alerts_account_active", "account_id", "acknowledged_at", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"))
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(10), nullable=False, default="medium")
    alert_type = Column("type", String(30), nullable=False, default="system")
    rule_id = Column(String(100))
    recommendations = Column(JSONB, nullable=False, default=list)
    source = Column(String(10), nullable=False, default="user")
    extra = Column("metadata", JSONB, nullable=False, default=dict)
    valid_from = Column(DateTime(timezone=True))
    valid_to = Column(DateTime(timezone=True))
    dedupe_key = Column(String(255), unique=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    acknowledged_at = Column(DateTime(timezone=True))
    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
