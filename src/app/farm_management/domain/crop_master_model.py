from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
import uuid

from .base import Base # Import Base from the same directory

class CropMasterModel(Base):
    __tablename__ = "cultivos_master"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    variety = Column(String(255))
    family = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<CropMasterModel(id={self.id}, name='{self.name}')>" 