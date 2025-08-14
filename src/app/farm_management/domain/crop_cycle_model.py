from sqlalchemy import Column, DateTime, Text, Date, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid

from .base import Base # Import Base from the same directory

class CropCycleModel(Base):
    __tablename__ = "cultivos_ciclos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    field_id = Column(UUID(as_uuid=True), ForeignKey("campos.id"), nullable=False)
    crop_master_id = Column(UUID(as_uuid=True), ForeignKey("cultivos_master.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<CropCycleModel(id={self.id}, field_id='{self.field_id}', crop_master_id='{self.crop_master_id}')>" 