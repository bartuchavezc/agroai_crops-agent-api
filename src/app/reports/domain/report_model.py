from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
import uuid

from .base import Base # Import Base from the same directory

class ReportModel(Base):
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_identifier = Column(String(255), nullable=False, index=True)
    analysis_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)
    image_urls = Column(ARRAY(String), nullable=True)
    raw_analysis_data = Column(JSONB, nullable=True)
    status = Column(String(50), nullable=False, default="PENDING_ANALYSIS")
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<ReportModel(id={self.id}, title='{self.title}', status='{self.status}')>" 