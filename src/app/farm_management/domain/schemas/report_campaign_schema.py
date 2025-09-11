from pydantic import BaseModel
from uuid import UUID

# For creating/linking a report to a crop cycle
class ReportCampaignLink(BaseModel):
    report_id: UUID
    crop_cycle_id: UUID

class ReportCampaignRead(ReportCampaignLink):
    # No extra fields typically, as it's a link table
    # but can include related object details if needed for specific use cases
    # report: Optional[Any] = None # Placeholder for ReportRead schema if needed
    # crop_cycle: Optional[Any] = None # Placeholder for CropCycleRead schema if needed
    pass

    class Config:
        from_attributes = True 