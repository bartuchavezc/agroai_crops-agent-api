# src/api/routes/upload_router.py
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from dependency_injector.wiring import inject, Provide

from src.app.container import Container
from src.app.utils.logger import get_logger
from src.app.storage.service.storage_service import StorageService
from src.app.reports.service.reports_service import ReportsService
from src.app.reports.domain.models import ReportCreate # Para crear el reporte
from src.api.schemas.upload_schemas import UploadImageResponse
from src.app.utils.errors import StorageError, InvalidInputError, CropAnalysisError
from src.app.utils.image_utils import (
    image_type_validation, 
    validate_image_size, 
    MAX_IMAGE_SIZE_BYTES
)

logger = get_logger(__name__)
router = APIRouter(
    prefix="/upload",
    tags=["Uploads"],
)

@router.post(
    "/image", 
    response_model=UploadImageResponse, 
    summary="Upload Crop Image and Create Initial Report",
    description="Receives an image, saves it, and creates an initial report entry. Images must be JPEG or PNG."
)
@inject
async def upload_crop_image(
    # Se pueden añadir otros campos de Form si son necesarios, ej: plot_id: Optional[str] = Form(None)
    image_file: UploadFile = File(..., description="Image file of the crop (JPEG or PNG)."),
    storage_service: StorageService = Depends(Provide[Container.storage.storage_service]),
    reports_service: ReportsService = Depends(Provide[Container.reports.reports_service]),
):
    """
    Handles image upload, saves the image using StorageService, and creates an initial report
    using ReportsService.
    """
    logger.info(f"Received image upload request: {image_file.filename}")

    image_data = await image_file.read()
    content_type = image_file.content_type # Still useful for logging or initial checks

    # Validate image type using the utility function
    # This will raise InvalidInputError if validation fails, which is caught below.
    try:
        image_type_validation(image_bytes=image_data, content_type=content_type, image_identifier=image_file.filename)
        logger.info(f"Image type validated for {image_file.filename}, content-type: {content_type}")
    except InvalidInputError as e:
        logger.warning(f"Image type validation failed for {image_file.filename}: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=e.message # Use message from the validation error
        )
    
    # Validate image size using the utility function
    try:
        validate_image_size(
            image_data_length=len(image_data), 
            max_size_bytes=MAX_IMAGE_SIZE_BYTES, 
            image_identifier=image_file.filename
        )
    except InvalidInputError as e:
        logger.warning(f"Image size validation failed for {image_file.filename}: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=e.message # Use message from the validation error
        )
    
    try:
        image_identifier = await storage_service.save_image(
            file_name=image_file.filename, 
            image_data=image_data, 
            content_type=content_type
        )
        logger.info(f"Image '{image_file.filename}' saved with identifier: {image_identifier}")

        # Crear el reporte inicial
        report_to_create = ReportCreate(
            image_identifier=image_identifier,
        )
        new_report = await reports_service.create_report(report_to_create)

        return UploadImageResponse(
            report_id=new_report.id,
            image_identifier=image_identifier,
            status=new_report.status, # Debería ser PENDING_ANALYSIS
            message="Image uploaded and initial report created successfully."
        )

    except StorageError as e:
        logger.error(f"Storage error during image upload '{image_file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to store image: {e.message}")
    except InvalidInputError as e: # Catches other InvalidInputErrors, e.g., from report creation
        logger.error(f"Invalid input error during report creation for '{image_file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid data for report creation: {e.message}")
    except CropAnalysisError as e: # Error base más genérico
        logger.error(f"CropAnalysisError during upload for '{image_file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"Unexpected error during image upload '{image_file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="An unexpected error occurred during image upload.") 