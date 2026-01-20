# src/action/storage/storage_service.py
"""
Storage service for file operations.
"""
from typing import Any, Dict, Optional, Tuple
import logging

from .interfaces import FileRepository
from src.shared.utils.errors import InvalidInputError, StorageError

logger = logging.getLogger(__name__)


class StorageService:
    """
    Service for handling file storage operations.
    Acts as an intermediary to the underlying storage repository.
    """

    def __init__(self, file_repository: FileRepository):
        """
        Initialize the storage service.

        Args:
            file_repository: File repository implementation
        """
        self.file_repository = file_repository
        logger.info("StorageService initialized")

    async def get_image_data(
        self,
        image_identifier: str
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Retrieve image data and metadata.

        Args:
            image_identifier: Unique image identifier

        Returns:
            Tuple of (image_bytes, metadata)
        
        Raises:
            InvalidInputError: If image not found
            StorageError: If retrieval fails
        """
        logger.debug(f"Retrieving image: {image_identifier}")
        
        try:
            retrieved_data = await self.file_repository.get_file_data(image_identifier)
            
            if retrieved_data is None:
                logger.warning(f"Image not found: {image_identifier}")
                raise InvalidInputError(f"Image not found: {image_identifier}")
            
            image_bytes, image_metadata = retrieved_data
            logger.info(f"Retrieved image: {image_identifier}")
            return image_bytes, image_metadata
            
        except InvalidInputError:
            raise
        except Exception as e:
            logger.error(f"Storage error for {image_identifier}: {e}", exc_info=True)
            raise StorageError(f"Storage error retrieving image: {image_identifier}")

    async def save_image(
        self,
        file_name: Optional[str],
        image_data: bytes,
        content_type: Optional[str] = None
    ) -> str:
        """
        Save image data to storage.

        Args:
            file_name: Original file name
            image_data: Image content as bytes
            content_type: Optional MIME type

        Returns:
            Unique identifier for the saved image

        Raises:
            StorageError: If saving fails
        """
        logger.debug(f"Saving image: {file_name}")
        
        try:
            image_identifier = await self.file_repository.save_file(
                file_name=file_name or "unnamed_image",
                file_data=image_data,
                content_type=content_type
            )
            
            logger.info(f"Image saved: {image_identifier} (original: {file_name})")
            return image_identifier
            
        except StorageError:
            raise
        except Exception as e:
            logger.error(f"Error saving image {file_name}: {e}", exc_info=True)
            raise StorageError(f"Error saving image: {e}")

    async def delete_image(self, image_identifier: str) -> bool:
        """
        Delete an image from storage.

        Args:
            image_identifier: Unique image identifier

        Returns:
            True if deleted successfully
        """
        try:
            result = await self.file_repository.delete_file(image_identifier)
            if result:
                logger.info(f"Deleted image: {image_identifier}")
            return result
        except Exception as e:
            logger.error(f"Error deleting image {image_identifier}: {e}")
            return False

    async def image_exists(self, image_identifier: str) -> bool:
        """
        Check if an image exists.

        Args:
            image_identifier: Unique image identifier

        Returns:
            True if image exists
        """
        return await self.file_repository.file_exists(image_identifier)

    async def get_image_metadata(self, image_identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get only the metadata for an image.

        Args:
            image_identifier: Unique image identifier

        Returns:
            Metadata dictionary or None
        """
        try:
            result = await self.file_repository.get_file_data(image_identifier)
            if result:
                _, metadata = result
                return metadata
            return None
        except Exception:
            return None
