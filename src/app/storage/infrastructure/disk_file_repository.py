import os
import mimetypes
from typing import Tuple, Dict, Any, Optional
import uuid

from src.app.storage.domain.repositories import FileRepository
from src.app.utils.logger import get_logger
from src.app.utils.errors import StorageError

logger = get_logger(__name__)

class DiskFileRepository(FileRepository):
    """
    Concrete implementation for retrieving files from a local disk.
    """

    def __init__(self, base_data_path: str):
        """
        Initializes the DiskFileRepository.

        Args:
            base_data_path: The absolute base path where files are stored.
                            Files will only be accessed within this directory.
        
        Raises:
            ValueError: If base_data_path is not a valid, existing directory.
        """
        if not os.path.isdir(base_data_path) or not os.path.exists(base_data_path):
            logger.error(f"Invalid base_data_path: {base_data_path}. Directory does not exist or is not a directory.")
            raise ValueError(f"Invalid base_data_path: {base_data_path}")
        self.base_data_path = os.path.abspath(base_data_path)
        logger.info(f"DiskFileRepository initialized with base path: {self.base_data_path}")

    async def get_file_data(self, identifier: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """
        Retrieves file data and its metadata from the local disk.

        The identifier is treated as a relative path from the base_data_path.
        It ensures that the resolved path is within the base_data_path to prevent
        accessing files outside the intended directory (directory traversal).

        Args:
            identifier: The relative path of the file from the base_data_path.

        Returns:
            A tuple containing the file content as bytes and a dictionary of metadata
            (e.g., 'content_type', 'file_size').
            Returns None if the file is not found, is outside the base path, or cannot be read.
        """
        try:
            # Sanitize the identifier to prevent directory traversal issues
            # os.path.normpath will resolve '..' and '.' components
            # os.path.join will correctly join paths
            relative_path = os.path.normpath(identifier.lstrip('/\\')) # Remove leading slashes
            
            if '..' in relative_path.split(os.path.sep):
                logger.warning(f"Attempt to access path with '..' components: {identifier}")
                return None

            full_path = os.path.join(self.base_data_path, relative_path)
            
            # Final check to ensure the resolved path is still within the base directory
            if not os.path.abspath(full_path).startswith(self.base_data_path):
                logger.warning(f"Attempt to access file outside base path: {full_path} (identifier: {identifier})")
                return None

            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                logger.warning(f"File not found or is not a file: {full_path} (identifier: {identifier})")
                return None

            with open(full_path, 'rb') as f:
                file_content = f.read()
            
            file_size = os.path.getsize(full_path)
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type is None:
                content_type = 'application/octet-stream' # Default if type cannot be guessed

            metadata = {
                'file_name': os.path.basename(full_path),
                'full_path': full_path,
                'content_type': content_type,
                'file_size': file_size,
            }
            logger.info(f"Successfully retrieved file: {full_path} (identifier: {identifier})")
            return file_content, metadata

        except IOError as e:
            logger.error(f"IOError reading file {identifier} (resolved to {full_path}): {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error retrieving file {identifier} (resolved to {full_path}): {e}", exc_info=True)
            return None

    async def save_file(self, file_name: Optional[str], file_data: bytes, content_type: Optional[str] = None) -> str:
        """
        Saves file data to the local disk within the base_data_path.
        Generates a unique filename using UUID to prevent collisions, preserving the original extension.

        Args:
            file_name: The original name of the file, used to extract the extension.
            file_data: The file content as bytes.
            content_type: Optional. The MIME type of the file (currently not used for naming but could be for metadata).

        Returns:
            The unique relative path (identifier) of the saved file within the base_data_path.
        
        Raises:
            StorageError: If saving the file fails due to IO or other issues.
        """
        try:
            original_extension = ""
            if file_name:
                _, original_extension = os.path.splitext(file_name)
                original_extension = original_extension.lower() # Ensure consistent extension casing
            
            # Generate a unique filename using UUID
            unique_filename = str(uuid.uuid4()) + original_extension
            
            # For now, save directly in base_data_path. Consider subdirectories for organization if many files.
            file_path = os.path.join(self.base_data_path, unique_filename)

            # Ensure the path is still within the base directory (should be, but as a safeguard)
            if not os.path.abspath(file_path).startswith(self.base_data_path):
                logger.error(f"Attempt to save file outside base path: {file_path}")
                raise StorageError(f"Cannot save file outside designated storage area.", error_code="STORAGE_PATH_ERROR")

            with open(file_path, 'wb') as f:
                f.write(file_data)
            
            logger.info(f"File saved successfully: {file_path} (original name: {file_name})")
            # The identifier returned is the unique filename, relative to base_data_path
            return unique_filename

        except IOError as e:
            logger.error(f"IOError saving file (original name: {file_name}): {e}")
            raise StorageError(f"Failed to save file due to an IO error: {e}", error_code="STORAGE_IO_ERROR")
        except Exception as e:
            logger.error(f"Unexpected error saving file (original name: {file_name}): {e}", exc_info=True)
            raise StorageError(f"An unexpected error occurred while saving file: {e}", error_code="STORAGE_UNEXPECTED_ERROR")

# Example Usage (for testing or direct instantiation if not using DI):
# if __name__ == '__main__':
#     import asyncio
#     # Create a dummy data directory and file for testing
#     test_data_path = os.path.join(os.path.dirname(__file__), 'test_data')
#     os.makedirs(test_data_path, exist_ok=True)
#     dummy_file_path = os.path.join(test_data_path, 'sample.txt')
#     with open(dummy_file_path, 'w') as f:
#         f.write("Hello, world!")

#     repo = DiskFileRepository(base_data_path=test_data_path)
    
#     async def main():
#         # Test retrieving an existing file
#         data, meta = await repo.get_file_data('sample.txt')
#         if data:
#             print(f"Content: {data.decode()}")
#             print(f"Metadata: {meta}")
        
#         # Test retrieving a non-existent file
#         result_non_existent = await repo.get_file_data('non_existent.txt')
#         if result_non_existent is None:
#             print("Non-existent file correctly not found.")

#         # Test directory traversal attempt (should fail)
#         result_traversal = await repo.get_file_data('../../../etc/passwd') # Example
#         if result_traversal is None:
#             print("Directory traversal attempt correctly blocked.")

#     asyncio.run(main())
#     # Clean up dummy file and directory
#     os.remove(dummy_file_path)
#     os.rmdir(test_data_path) 