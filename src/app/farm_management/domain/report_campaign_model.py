from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from .base import Base # Import Base from the same directory

class ReportCampaignModel(Base):
    __tablename__ = "report_campaigns"

    report_id = Column(UUID(as_uuid=True), ForeignKey("reports.id"), primary_key=True)
    crop_cycle_id = Column(UUID(as_uuid=True), ForeignKey("cultivos_ciclos.id"), primary_key=True)

    def __repr__(self):
        return f"<ReportCampaignModel(report_id={self.report_id}, crop_cycle_id={self.crop_cycle_id})>" 