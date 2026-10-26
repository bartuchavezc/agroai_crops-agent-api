"""What lets the assistant come to the person instead of waiting: summaries for whoever is away, the phones it can
reach (Web Push), what each person wants to be told and when, and the log of every time it decided to speak — or to
stay quiet."""
import uuid

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.shared.database import Base
from src.shared.domain.base import utcnow

DIGEST_KINDS = ("daily", "weekly")
NUDGE_OUTCOMES = ("sent", "silent", "budget", "quiet_hours", "failed")


class Digest(Base):
    """A summary of a day or a week of one field, written by the agent from the records, the analyses and the
    weather: facts, gaps and questions, never made-up scores. `data` keeps the facts it was written from."""
    __tablename__ = "digests"
    __table_args__ = (
        CheckConstraint(f"kind IN {DIGEST_KINDS}", name="kind_valid"),
        UniqueConstraint("account_id", "field_id", "kind", "local_date", name="uq_digests_field_kind_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    field_id = Column(UUID(as_uuid=True), ForeignKey("fields.id", ondelete="CASCADE"), index=True)  # None: before
    kind = Column(String(10), nullable=False)
    local_date = Column(Date, nullable=False)  # the day (or the week's last day) it covers, in the account's time
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    title = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    data = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class PushSubscription(Base):
    """A browser/phone that accepted notifications (the Web Push subscription as the browser gives it)."""
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    user_agent = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_success_at = Column(DateTime(timezone=True))
    failures = Column(Integer, nullable=False, default=0)


class NotificationPreferences(Base):
    """Per person: how much the assistant may interrupt, when not, and which summaries they get."""
    __tablename__ = "notification_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    nudges_enabled = Column(Boolean, nullable=False, default=True)
    max_nudges_per_day = Column(Integer, nullable=False, default=2)
    quiet_start = Column(String(5), nullable=False, default="21:00")  # local HH:MM
    quiet_end = Column(String(5), nullable=False, default="07:30")
    daily_digest = Column(Boolean)  # None: on (everyone in the account gets the summary of each field)
    weekly_digest = Column(Boolean)
    push_enabled = Column(Boolean, nullable=False, default=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class NudgeLog(Base):
    """Each time the assistant weighed the account's signals: what it saw, what it decided and why. Silence is a
    decision too, and the log is what keeps it from repeating itself."""
    __tablename__ = "nudge_log"
    __table_args__ = (
        CheckConstraint(f"outcome IN {NUDGE_OUTCOMES}", name="outcome_valid"),
        Index("ix_nudge_log_account_created", "account_id", "created_at"),
        Index("ix_nudge_log_user_created", "user_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    window = Column(String(10), nullable=False)  # morning | evening | urgent
    signals = Column(JSONB, nullable=False, default=list)
    signal_keys = Column(JSONB, nullable=False, default=list)  # what it already spoke about (dedupe)
    outcome = Column(String(12), nullable=False)
    kind = Column(String(20))  # ask | recommend | warn | info
    message = Column(Text)
    reason = Column(Text)  # the model's own why (also for staying quiet)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
