from pydantic import BaseModel


class ImageAnalysisRequest(BaseModel):
    report_id: str
    image_identifier: str