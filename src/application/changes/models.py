"""A change proposal: several writes the agent prepared, shown to the user before anything changes."""
import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

PROPOSAL_STATUSES = ("pending", "applied", "rejected", "failed")


class ChangeProposal(Base):
    __tablename__ = "change_proposals"
    __table_args__ = (
        CheckConstraint(f"status IN {PROPOSAL_STATUSES}", name="status_valid"),
        Index("ix_change_proposals_account_status", "account_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), index=True)
    title = Column(String(255), nullable=False)
    operations = Column(JSONB, nullable=False, default=list)
    preview = Column(JSONB, nullable=False, default=list)
    status = Column(String(10), nullable=False, default="pending")
    result = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    decided_at = Column(DateTime(timezone=True))
