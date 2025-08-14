"""
Image analysis API route for FastAPI.
"""
import traceback
from fastapi import APIRouter, Depends, HTTPException, status, Body
from dependency_injector.wiring import inject, Provide

from src.app.container import Container
from src.app.utils.logger import get_logger
from src.api.schemas.image_analysis_request import ImageAnalysisRequest
from src.app.analysis.service.segmenter import SegmenterService
from src.app.analysis.service.captioner import CaptionerService
from src.app.analysis.service.reasoning import ReasoningService
from src.app.reports.service.reports_service import ReportsService
from src.app.reports.domain.models import ReportUpdate
from src.app.utils.image_utils import image_to_base64, load_image_bytes_to_pil, image_type_validation
from src.app.analysis.domain.parsers import parse_llm_diagnosis_output
from src.app.utils.errors import (
    MissingInputError,
    InvalidInputError,
    CropAnalysisError,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/analyze",
    tags=["Analysis"],
)

@router.post("", summary="Analyze Crop Image for Report", description="Validates an existing report, analyzes an image from storage, and updates the report with analysis results.")
@inject
async def analyze_image_endpoint(
    request_data: ImageAnalysisRequest = Body(..., description="Report ID and Image Identifier for analysis."),
    segmenter: SegmenterService = Depends(Provide[Container.analysis.segmenter_service]),
    captioner: CaptionerService = Depends(Provide[Container.analysis.captioner_service]),
    reasoner: ReasoningService = Depends(Provide[Container.analysis.reasoner_service]),
    reports_service: ReportsService = Depends(Provide[Container.reports.reports_service]),
    storage_service = Depends(Provide[Container.storage.storage_service])
):
    """
    Retrieves an existing report by report_id, fetches an image from storage using image_identifier,
    runs an analysis pipeline, and updates the report with the new analysis results.
    
    Returns:
        JSON with analysis results including caption, diagnosis, and the report_id.
    """
    report_id = request_data.report_id
    image_identifier = request_data.image_identifier

    if not report_id or not image_identifier:
        raise MissingInputError("Both report_id and image_identifier must be provided.")

    try:
        report = await reports_service.get_report_by_id(report_id)
        if not report:
            raise InvalidInputError(f"Report with ID {report_id} not found.")

        image_bytes, image_metadata = await storage_service.get_image_data(image_identifier)
        if not image_bytes:
            raise InvalidInputError(f"Image not found or empty for identifier: {image_identifier}")

        image_content_type = image_metadata.get('content_type', '')
        image_type_validation(image_bytes, image_content_type, image_identifier)
        
        image = load_image_bytes_to_pil(image_bytes, image_identifier=image_identifier)
        
        segmentation_result = segmenter.segment_image(image)
        caption = captioner.generate_caption(image=segmentation_result.overlay)
        llm_diagnosis_str = reasoner.generate_reasoning(
            caption=caption, 
            affected_percentage=segmentation_result.affected_percentage
        )
        
        parsed_llm_diagnosis = parse_llm_diagnosis_output(llm_diagnosis_str)

        overlayed_image_b64 = image_to_base64(segmentation_result.overlay)
        report_recommendations = parsed_llm_diagnosis.get("general_diagnosis", llm_diagnosis_str)
        if not isinstance(report_recommendations, str):
             report_recommendations = str(report_recommendations)

        new_raw_analysis_data = {
            "segmentation_metadata": segmentation_result.metadata,
            "affected_percentage": segmentation_result.affected_percentage,
            "llm_structured_diagnosis": parsed_llm_diagnosis,
            "llm_raw_output": llm_diagnosis_str,
            "analyzed_image_identifier": image_identifier
        }

        report_update_data = ReportUpdate(
            summary=caption,
            recommendations=report_recommendations,
            raw_analysis_data=new_raw_analysis_data,
            status="ANALYSIS_COMPLETED" 
        )
        await reports_service.update_report(
            report_id=report_id, 
            report_update=report_update_data
        )
        logger.info(f"Report {report_id} updated with new analysis for image {image_identifier}")

        return {
            "status": "success",
            "report_id": str(report_id),
            "caption": caption,
            "diagnosis": llm_diagnosis_str,
            "overlayed_image_b64": overlayed_image_b64,
            "metadata_from_segmentation": segmentation_result.metadata or {}
        }
        
    except CropAnalysisError as e:
        logger.error(f"{e.error_code}: {str(e)} during analysis for report {report_id}, image {image_identifier}")
        raise
        
    except Exception as e:
        logger.error(f"Unexpected error during analysis for report {report_id}, image {image_identifier}: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during analysis: {str(e)}"
        ) 