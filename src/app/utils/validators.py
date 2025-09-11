import io
from PIL import Image
from src.app.utils.errors import InvalidInputError

"""
Validation utilities for API requests and data processing.
"""

def validate_image_format(file):
    """
    Validate if the file is an acceptable image format.
    
    Args:
        file: The file object to validate
        
    Returns:
        bool: True if the file is valid, False otherwise
    """
    # Check file extension
    if not file.filename or '.' not in file.filename:
        return False
    
    ext = file.filename.rsplit('.', 1)[1].lower()
    if ext not in ['jpg', 'jpeg', 'png']:
        return False
    
    # Could add additional checks here like:
    # - File size
    # - Image dimensions
    # - Image content validation
    
    return True

def image_type_validation(image_bytes: bytes, content_type: str, image_identifier: str):
    """
    Validates if the provided image is of an acceptable type (JPEG or PNG).

    Args:
        image_bytes: The raw bytes of the image.
        content_type: The content type string, typically from image metadata (e.g., 'image/jpeg').
        image_identifier: A string identifying the image (e.g., filename or URL) for error messages.

    Raises:
        InvalidInputError: If the image type is not JPEG or PNG, or cannot be identified.
    """
    if content_type and content_type in ["image/jpeg", "image/png"]:
        # Content type is known and valid, no need for content inspection
        return

    # If content_type is missing, not 'image/jpeg', or not 'image/png', try to identify from content
    try:
        temp_pil_image = Image.open(io.BytesIO(image_bytes))
        if temp_pil_image.format and temp_pil_image.format.upper() in ['JPEG', 'PNG']:
            # Identified as JPEG or PNG from content
            return 
        else:
            # Content identified, but not as JPEG or PNG
            detected_format = temp_pil_image.format if temp_pil_image.format else "unknown"
            raise InvalidInputError(
                f"Invalid image type for '{image_identifier}' based on content inspection. "
                f"Must be JPEG or PNG. Detected: {detected_format}"
            )
    except Exception as e: # Catches PIL.UnidentifiedImageError, and other PIL related errors
        # logger.debug(f"PIL error during image type validation for '{image_identifier}': {e}") # Optional: log original error
        raise InvalidInputError(
            f"Cannot identify image type or invalid image format for '{image_identifier}' after content inspection. "
            f"Must be JPEG or PNG."
        ) 

def validate_api_params(params, required_fields=None, optional_fields=None):
    """
    Validate API request parameters.
    
    Args:
        params (dict): Parameters to validate
        required_fields (list): List of required field names
        optional_fields (list): List of optional field names
        
    Returns:
        tuple: (is_valid, error_message)
    """
    if required_fields is None:
        required_fields = []
    
    if optional_fields is None:
        optional_fields = []
    
    # Check required fields
    for field in required_fields:
        if field not in params or not params[field]:
            return False, f"Missing required field: {field}"
    
    # Check for unknown fields
    allowed_fields = required_fields + optional_fields
    for field in params:
        if field not in allowed_fields:
            return False, f"Unknown field: {field}"
    
    return True, None 