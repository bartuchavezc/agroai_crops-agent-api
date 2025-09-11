from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional

class FileRepository(ABC):
    """
    Repository for retrieving and saving file data from/to a storage system.
    """

    @abstractmethod
    async def get_file_data(self, identifier: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """
        Retrieves file data and its metadata from storage.

        Args:
            identifier: A unique identifier for the file (e.g., file path, URI, or ID).

        Returns:
            A tuple containing the file content as bytes and a dictionary of metadata.
            Returns None if the file is not found or cannot be retrieved.
        """
        pass

    @abstractmethod
    async def save_file(self, file_name: Optional[str], file_data: bytes, content_type: Optional[str] = None) -> str:
        """
        Saves file data to the storage and returns a unique identifier for the saved file.

        Args:
            file_name: The desired file name. If None, an identifier might be generated.
            file_data: The file content as bytes.
            content_type: Optional. The MIME type of the file.

        Returns:
            A unique identifier (e.g., path or ID) for the saved file.
        
        Raises:
            StorageError: If saving the file fails.
        """
        pass

    # You could add other common file operations here if needed, e.g.:
    # @abstractmethod
    # async def file_exists(self, identifier: str) -> bool:
    #     pass
    #
    # @abstractmethod
    # async def get_file_metadata(self, identifier: str) -> Optional[Dict[str, Any]]:
    #     pass 