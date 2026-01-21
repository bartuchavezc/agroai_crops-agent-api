# src/auth/domain/models.py
"""
User domain model for authentication.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship
import uuid
from passlib.context import CryptContext

from src.shared.database import shared_metadata

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Base for User-related tables, using shared metadata
Base = declarative_base(metadata=shared_metadata)


class Account(Base):
    """Account model for multi-tenancy support."""
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship to users
    users = relationship("User", back_populates="account")


class User(Base):
    """User model for authentication and authorization."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    role = Column(String(50), nullable=True)
    is_enrolled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship to account
    account = relationship("Account", back_populates="users")
    
    # Relationship to profile (one-to-one)
    profile = relationship("UserProfile", back_populates="user", uselist=False)

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Hash a password."""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash."""
        return pwd_context.verify(plain_password, hashed_password)


class UserProfile(Base):
    """User profile model for onboarding and agent personalization."""
    __tablename__ = "user_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    
    # JSON completo del formulario de onboarding
    form = Column(JSONB, nullable=False)
    
    # Categorías calculadas basadas en respuestas dominantes
    experience = Column(String(50))   # "novice", "intermediate", "expert"
    goal = Column(String(50))         # "self_consumption", "local_market", "premium_export"
    risk = Column(String(50))         # "low", "balanced", "high"
    philosophy = Column(String(50))   # "organic", "integrated", "traditional"
    
    # Perfil calculado para el comportamiento del agente
    profile = Column(String(50))      # "guardian", "purist", "alchemist", "professional"
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship to user
    user = relationship("User", back_populates="profile")
