from typing import Tuple, Dict, Any, Optional

from src.app.storage.domain.repositories import FileRepository
from src.app.utils.logger import get_logger
from src.app.utils.errors import InvalidInputError, StorageError

logger = get_logger(__name__)

class StorageService:
    """
    Service for handling file storage operations, acting as an intermediary
    to the underlying storage repository.
    """

    def __init__(self, file_repository: FileRepository):
        """
        Initializes the StorageService.

        Args:
            file_repository: An instance of a class that implements FileRepository.
        """
        self.file_repository = file_repository
        logger.info("StorageService initialized.")

    async def get_image_data(self, image_identifier: str) -> Tuple[bytes, Dict[str, Any]]:
        """
        Retrieves image data and metadata using the configured file repository.

        Args:
            image_identifier: The unique identifier for the image.

        Returns:
            A tuple containing the image content as bytes and a dictionary of metadata.
        
        Raises:
            InvalidInputError: If the image cannot be found.
            StorageError: If an unexpected error occurs during retrieval.
        """
        logger.debug(f"Attempting to retrieve image data for identifier: {image_identifier}")
        try:
            retrieved_data = await self.file_repository.get_file_data(image_identifier)
            if retrieved_data is None:
                logger.warning(f"Image not found or access denied for identifier: {image_identifier}")
                raise InvalidInputError(f"Image not found with identifier: {image_identifier}")
            
            image_bytes, image_metadata = retrieved_data
            logger.info(f"Successfully retrieved image data for identifier: {image_identifier}")
            return image_bytes, image_metadata
        except InvalidInputError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in StorageService while getting image {image_identifier}: {e}", exc_info=True)
            raise StorageError(f"An unexpected storage error occurred while retrieving image: {image_identifier}")

    async def save_image(self, file_name: Optional[str], image_data: bytes, content_type: Optional[str] = None) -> str:
        """
        Saves image data using the configured file repository.

        Args:
            file_name: The original name of the image file.
            image_data: The image content as bytes.
            content_type: Optional. The MIME type of the image.

        Returns:
            The unique identifier for the saved image.

        Raises:
            StorageError: If saving the image fails.
        """
        logger.debug(f"Attempting to save image (original name: {file_name})")
        try:
            image_identifier = await self.file_repository.save_file(
                file_name=file_name, 
                file_data=image_data, 
                content_type=content_type
            )
            logger.info(f"Image saved successfully with identifier: {image_identifier} (original name: {file_name})")
            return image_identifier
        except StorageError:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in StorageService while saving image (original name: {file_name}): {e}", exc_info=True)
            raise StorageError(f"An unexpected error occurred while saving image: {e}")

# Example of how you might define AppError in src/app/utils/errors.py if it doesn't exist
# class AppError(Exception):
#     def __init__(self, message: str, error_code: str = "APP_ERROR"):
#         super().__init__(message)
#         self.error_code = error_code
#         self.message = message
#     def __str__(self):
#         return f"[{self.error_code}]: {self.message}" 