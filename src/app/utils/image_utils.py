from PIL import Image, ImageEnhance, UnidentifiedImageError
import io
import numpy as np
import base64
import logging

from src.app.utils.errors import ImagePreprocessingError, InvalidInputError

logger = logging.getLogger(__name__)

# --- Constants for Image Validation ---
MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024
# You could also make these configurable via environment variables if needed
# MAX_IMAGE_SIZE_BYTES = int(os.environ.get("MAX_IMAGE_SIZE_BYTES", 10 * 1024 * 1024))

def preprocess_image(image_bytes, target_size=(384, 384), contrast_factor=1.2):
    """
    Preprocess an image for model input:
    - Converts to RGB
    - Adjusts contrast
    - Resizes to target size
    - Normalizes to 0-1 range
    - Returns a normalized numpy array ready for the model
    
    Raises:
        ImagePreprocessingError: If preprocessing fails
    """
    try:
        # Load image and force RGB
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        # Adjust contrast (optional)
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(contrast_factor)

        # Resize image
        image = image.resize(target_size, Image.Resampling.LANCZOS)

        # Convert to numpy array and normalize to 0-1
        image_array = np.array(image, dtype=np.float32) / 255.0
        
        # Normalize with ImageNet values (optional - can be removed if not needed)
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        image_array = (image_array - mean) / std
        
        # Transpose to channels-first format: (H, W, C) -> (C, H, W)
        image_array = np.transpose(image_array, (2, 0, 1))
        
        # Add batch dimension: (C, H, W) -> (1, C, H, W)
        image_array = np.expand_dims(image_array, axis=0)
        
        return image_array
    except Exception as e:
        logger.error(f"Image preprocessing failed: {str(e)}")
        raise ImagePreprocessingError(f"Failed to preprocess image: {str(e)}") from e

def mask_to_base64(mask) -> str:
    """
    Convert a segmentation mask to base64 string.
    
    Args:
        mask: Segmentation mask (numpy array or list)
        
    Returns:
        str: Base64 encoded string of the mask image
    """
    # Convert list to numpy array if needed
    if not isinstance(mask, np.ndarray):
        mask = np.array(mask)
    
    # Normalize mask to 0-255 range
    if mask.dtype != np.uint8:
        mask = (mask * 255).astype(np.uint8)
    
    # Create RGB mask image (red highlight)
    if len(mask.shape) == 2:
        h, w = mask.shape
        rgb_mask = np.zeros((h, w, 3), dtype=np.uint8)
        rgb_mask[mask > 0] = [255, 0, 0]  # Red for affected areas
    else:
        rgb_mask = mask
    
    # Convert to PIL and then to bytes
    img = Image.fromarray(rgb_mask)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    
    # Convert to base64
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def image_to_base64(image):
    """
    Convert a PIL image to base64 string
    
    Args:
        image: PIL Image
        
    Returns:
        str: Base64 encoded string of the image
    """
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')

def load_image_bytes_to_pil(image_bytes: bytes, image_identifier: str = "image") -> Image.Image:
    """
    Loads image bytes into a PIL Image object and converts it to RGB.

    Args:
        image_bytes: The raw bytes of the image.
        image_identifier: A string identifying the image (e.g., filename or URL) for error messages.

    Returns:
        PIL.Image.Image: The loaded image, converted to RGB.

    Raises:
        ImagePreprocessingError: If the image cannot be opened or converted (using existing error type from this file).
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
        return image
    except UnidentifiedImageError as e:
        logger.error(f"Cannot open image '{image_identifier}': {e}")
        raise ImagePreprocessingError(f"Cannot open or identify image format for '{image_identifier}'. It may be corrupted or not a supported image type by PIL.") from e
    except Exception as e:
        logger.error(f"Error converting image '{image_identifier}' to PIL RGB: {e}")
        raise ImagePreprocessingError(f"Failed to load and convert image '{image_identifier}' to RGB: {str(e)}") from e

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
        return

    try:
        temp_pil_image = Image.open(io.BytesIO(image_bytes))
        if temp_pil_image.format and temp_pil_image.format.upper() in ['JPEG', 'PNG']:
            return 
        else:
            detected_format = temp_pil_image.format if temp_pil_image.format else "unknown"
            raise InvalidInputError(
                f"Invalid image type for '{image_identifier}' based on content inspection. "
                f"Must be JPEG or PNG. Detected: {detected_format}"
            )
    except UnidentifiedImageError:
        raise InvalidInputError(
            f"Cannot identify image type for '{image_identifier}' (UnidentifiedImageError). "
            f"Must be JPEG or PNG. Ensure it is a valid image file."
        )
    except Exception as e:
        raise InvalidInputError(
            f"Error during image type validation for '{image_identifier}': {str(e)}. "
            f"Must be JPEG or PNG."
        )

def validate_image_size(image_data_length: int, max_size_bytes: int, image_identifier: str = "image"):
    """
    Validates if the image data length (size) is within the allowed limit.

    Args:
        image_data_length: The length of the image data in bytes.
        max_size_bytes: The maximum allowed size in bytes.
        image_identifier: A string identifying the image for error messages.

    Raises:
        InvalidInputError: If the image size exceeds max_size_bytes.
    """
    if image_data_length > max_size_bytes:
        max_size_mb = max_size_bytes / (1024 * 1024)
        logger.warning(
            f"Image '{image_identifier}' size ({image_data_length} bytes) exceeds limit of {max_size_mb:.2f} MB."
        )
        raise InvalidInputError(
            f"Image file size for '{image_identifier}' exceeds the limit of {max_size_mb:.2f} MB."
        )
    logger.debug(f"Image '{image_identifier}' size ({image_data_length} bytes) is within limits.")