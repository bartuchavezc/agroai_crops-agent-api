from sqlalchemy import Column, DateTime, String, Integer, Date, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from .base import Base # Import Base from the same directory

class AccountModel(Base):
    __tablename__ = "accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_name = Column(String(255), nullable=False)
    plan = Column(String(50))
    max_fields = Column(Integer)
    subscription_start = Column(Date)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<AccountModel(id={self.id}, org_name='{self.org_name}')>" 