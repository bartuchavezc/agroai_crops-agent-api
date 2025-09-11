from pydantic import BaseModel, Field
from uuid import UUID

class UploadImageResponse(BaseModel):
    report_id: UUID
    image_identifier: str
    status: str = Field(default="PENDING_ANALYSIS")
    message: str 