"""
Account, user and profile models.
"""
import uuid

import bcrypt
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from src.shared.database import Base
from src.shared.domain.base import utcnow
from src.shared.domain.locale import COUNTRIES, DEFAULT_COUNTRY, default_locale, default_timezone

# bcrypt only looks at the first 72 bytes of a password; longer ones are rejected at the schema level.
BCRYPT_MAX_PASSWORD_BYTES = 72

ROLE_OWNER = "owner"
ROLE_TECNICO = "tecnico"
ROLE_STAFF = "staff"
ROLES = (ROLE_OWNER, ROLE_TECNICO, ROLE_STAFF)
MANAGER_ROLES = (ROLE_OWNER, ROLE_TECNICO)


class Account(Base):
    """An account groups the users (family, team) that share fields and agent memory."""
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    users = relationship("User", back_populates="account")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="role_valid"),
        CheckConstraint(f"country IN {COUNTRIES}", name="country_valid"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String(50), nullable=False, default=ROLE_OWNER)
    # Where the person is and how to talk to them (voice of the agent, local time). Existing users stay in Argentina.
    country = Column(String(2), nullable=False, default=DEFAULT_COUNTRY, server_default=DEFAULT_COUNTRY)
    timezone = Column(
        String(64), nullable=False, default=default_timezone(DEFAULT_COUNTRY),
        server_default=default_timezone(DEFAULT_COUNTRY),
    )
    locale = Column(
        String(10), nullable=False, default=default_locale(DEFAULT_COUNTRY),
        server_default=default_locale(DEFAULT_COUNTRY),
    )
    is_enrolled = Column(Boolean, default=False, nullable=False)
    # A removed member keeps their row (authorship of events/reports) but can no longer log in.
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    # Embedded in every JWT ("tv"); bumping it revokes all tokens issued before (password change, removal).
    token_version = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    account = relationship("Account", back_populates="users")
    profile = relationship("UserProfile", back_populates="user", uselist=False)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
        except ValueError:  # over 72 bytes, or a malformed stored hash
            return False


class UserProfile(Base):
    """Onboarding questionnaire and the derived profile used to tune the agent."""
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    form = Column(JSONB, nullable=False)
    experience = Column(String(50))
    goal = Column(String(50))
    risk = Column(String(50))
    philosophy = Column(String(50))
    profile = Column(String(50))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    user = relationship("User", back_populates="profile")
