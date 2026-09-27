"""
Account, user and profile models.
"""
import uuid

from passlib.context import CryptContext
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from src.shared.database import Base
from src.shared.domain.base import utcnow

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String(50), nullable=False, default=ROLE_OWNER)
    is_enrolled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    account = relationship("Account", back_populates="users")
    profile = relationship("UserProfile", back_populates="user", uselist=False)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)


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
