# src/action/api/analyze_router.py
"""
Image analysis API route.
"""
import traceback
from fastapi import APIRouter, Depends, HTTPException, status, Body
from dependency_injector.wiring import inject, Provide
from pydantic import BaseModel
from uuid import UUID
import logging

from src.shared.utils.errors import (
    MissingInputError,
    InvalidInputError,
    CropAnalysisError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analyze", tags=["Analysis"])


class ImageAnalysisRequest(BaseModel):
    """Request schema for image analysis."""
    report_id: UUID
    image_identifier: str


@router.post("", summary="Analyze Crop Image")
@inject
async def analyze_image_endpoint(
    request_data: ImageAnalysisRequest = Body(...),
    diagnosis_service = Depends(Provide["agent.diagnosis_service"]),
    reports_service = Depends(Provide["action.reports_service"]),
    storage_service = Depends(Provide["action.storage_service"]),
    captioner_service = Depends(Provide["action.captioner_service"]),
    segmenter_service = Depends(Provide["action.segmenter_service"]),
):
    """
    Analyze a crop image and update the associated report with results.
    
    Steps:
    1. Validate report exists
    2. Retrieve image from storage
    3. Run segmentation
    4. Generate caption
    5. Run diagnosis
    6. Update report with results
    """
    report_id = request_data.report_id
    image_identifier = request_data.image_identifier

    if not report_id or not image_identifier:
        raise MissingInputError("Both report_id and image_identifier must be provided.")

    try:
        # Validate report exists
        report = await reports_service.get_report_by_id(report_id)
        if not report:
            raise InvalidInputError(f"Report with ID {report_id} not found.")

        # Get image data
        image_bytes, image_metadata = await storage_service.get_image_data(image_identifier)
        if not image_bytes:
            raise InvalidInputError(f"Image not found: {image_identifier}")

        # Run segmentation (if available)
        affected_percentage = 0.0
        segmentation_metadata = {}
        
        if segmenter_service:
            from PIL import Image
            import io
            image = Image.open(io.BytesIO(image_bytes))
            segmentation_result = segmenter_service.segment_image(image)
            affected_percentage = segmentation_result.affected_percentage
            segmentation_metadata = segmentation_result.metadata or {}
        
        # Generate caption (if available)
        caption = "Imagen de cultivo sin descripción disponible"
        if captioner_service:
            caption = captioner_service.generate_caption(image=image)
        
        # Run diagnosis
        diagnosis_result = await diagnosis_service.diagnose(
            caption=caption,
            affected_percentage=affected_percentage,
        )
        
        # Update report
        from ..reports.schemas import ReportUpdate
        report_update = ReportUpdate(
            summary=caption,
            recommendations=diagnosis_result.get("diagnosis", ""),
            raw_analysis_data={
                "segmentation_metadata": segmentation_metadata,
                "affected_percentage": affected_percentage,
                "diagnosis": diagnosis_result,
                "analyzed_image_identifier": image_identifier,
            },
            status="ANALYSIS_COMPLETED"
        )
        
        await reports_service.update_report(report_id, report_update)
        logger.info(f"Report {report_id} updated with analysis results")

        return {
            "status": "success",
            "report_id": str(report_id),
            "caption": caption,
            "diagnosis": diagnosis_result.get("diagnosis", ""),
            "severity": diagnosis_result.get("severity", "unknown"),
            "recommendations": diagnosis_result.get("recommendations", []),
            "metadata": {
                "affected_percentage": affected_percentage,
                "rules_triggered": diagnosis_result.get("metadata", {}).get("rules_triggered", 0),
            }
        }
        
    except CropAnalysisError as e:
        logger.error(f"{e.error_code}: {str(e)}")
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during analysis: {str(e)}"
        )
