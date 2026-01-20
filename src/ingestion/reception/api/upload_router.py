# src/ingestion/reception/api/upload_router.py
"""
File upload reception endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from dependency_injector.wiring import inject, Provide
from pydantic import BaseModel
from uuid import UUID

from src.shared.utils import get_logger
from src.shared.utils.errors import StorageError, InvalidInputError, CropAnalysisError

logger = get_logger(__name__)

router = APIRouter(prefix="/upload", tags=["Uploads"])


# Response schema
class UploadImageResponse(BaseModel):
    """Response schema for image upload."""
    report_id: UUID
    image_identifier: str
    status: str
    message: str


# Image validation constants
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/jpg"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def validate_image_type(image_bytes: bytes, content_type: str, filename: str) -> None:
    """
    Validate image type using content-type and magic bytes.
    
    Raises:
        InvalidInputError: If image type is not supported
    """
    # Check content type
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise InvalidInputError(
            f"Unsupported content type: {content_type}. Allowed: {ALLOWED_CONTENT_TYPES}"
        )
    
    # Check file extension
    if filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext and ext not in ALLOWED_EXTENSIONS:
            raise InvalidInputError(
                f"Unsupported file extension: {ext}. Allowed: {ALLOWED_EXTENSIONS}"
            )
    
    # Check magic bytes
    if len(image_bytes) < 8:
        raise InvalidInputError("Image file is too small to be valid")
    
    # JPEG magic bytes: FF D8 FF
    # PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
    is_jpeg = image_bytes[:3] == b'\xff\xd8\xff'
    is_png = image_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    
    if not (is_jpeg or is_png):
        raise InvalidInputError(
            "Invalid image format. Only JPEG and PNG are supported."
        )


def validate_image_size(image_data_length: int, max_size: int, filename: str) -> None:
    """
    Validate image size.
    
    Raises:
        InvalidInputError: If image is too large
    """
    if image_data_length > max_size:
        raise InvalidInputError(
            f"Image '{filename}' is too large ({image_data_length / 1024 / 1024:.2f}MB). "
            f"Maximum size is {max_size / 1024 / 1024:.2f}MB."
        )


@router.post(
    "/image",
    response_model=UploadImageResponse,
    summary="Upload Crop Image",
    description="Upload an image and create an initial report entry. Images must be JPEG or PNG."
)
@inject
async def upload_crop_image(
    image_file: UploadFile = File(..., description="Image file of the crop (JPEG or PNG)."),
    storage_service = Depends(Provide["action.storage_service"]),
    reports_service = Depends(Provide["action.reports_service"]),
):
    """
    Handle image upload, save the image, and create an initial report.
    """
    logger.info(f"Received image upload request: {image_file.filename}")

    image_data = await image_file.read()
    content_type = image_file.content_type

    # Validate image type
    try:
        validate_image_type(
            image_bytes=image_data,
            content_type=content_type,
            filename=image_file.filename
        )
        logger.info(f"Image type validated for {image_file.filename}")
    except InvalidInputError as e:
        logger.warning(f"Image type validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=e.message
        )
    
    # Validate image size
    try:
        validate_image_size(
            image_data_length=len(image_data),
            max_size=MAX_IMAGE_SIZE_BYTES,
            filename=image_file.filename
        )
    except InvalidInputError as e:
        logger.warning(f"Image size validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=e.message
        )
    
    try:
        # Save image
        image_identifier = await storage_service.save_image(
            file_name=image_file.filename,
            image_data=image_data,
            content_type=content_type
        )
        logger.info(f"Image saved with identifier: {image_identifier}")

        # Create initial report
        from src.action.reports.schemas import ReportCreate
        report_to_create = ReportCreate(image_identifier=image_identifier)
        new_report = await reports_service.create_report(report_to_create)

        return UploadImageResponse(
            report_id=new_report.id,
            image_identifier=image_identifier,
            status=new_report.status,
            message="Image uploaded and initial report created successfully."
        )

    except StorageError as e:
        logger.error(f"Storage error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store image: {e.message}"
        )
    except InvalidInputError as e:
        logger.error(f"Invalid input error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid data: {e.message}"
        )
    except CropAnalysisError as e:
        logger.error(f"CropAnalysisError: {e}", exc_info=True)
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during image upload."
        )
