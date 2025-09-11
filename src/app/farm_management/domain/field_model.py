from sqlalchemy import Column, DateTime, String, Text, Float, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from .base import Base # Import Base from the same directory

class FieldModel(Base):
    __tablename__ = "campos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    city = Column(String(255), index=True)
    soil_type = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<FieldModel(id={self.id}, name='{self.name}')>" 