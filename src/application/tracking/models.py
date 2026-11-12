"""The agent's own tracking plan of a lot: the stages it expects (as windows, not dates), the key moments, the risks,
and the checks it will ask for — written and corrected by the agent, read by the person. It never turns into a list
of chores with fixed dates for the person: what the person is asked for goes through the proactive check, paced by
their tracking intensity."""
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow


class LotTrackingPlan(Base):
    __tablename__ = "lot_tracking_plans"
    __table_args__ = (UniqueConstraint("lot_id", name="uq_lot_tracking_plans_lot"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(UUID(as_uuid=True), ForeignKey("lots.id", ondelete="CASCADE"), nullable=False)
    content = Column(JSONB, nullable=False, default=dict)  # TrackingPlanContent
    revisions = Column(JSONB, nullable=False, default=list)  # [PlanRevision], oldest first
    version = Column(Integer, nullable=False, default=1)
    last_observation_at = Column(DateTime(timezone=True))  # the last observation that corrected it
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
