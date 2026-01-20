# src/action/storage/interfaces.py
"""
Storage interface definitions.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class FileRepository(ABC):
    """Abstract interface for file storage operations."""
    
    @abstractmethod
    async def save_file(
        self,
        file_name: str,
        file_data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Save a file to storage.
        
        Args:
            file_name: Original file name
            file_data: File content as bytes
            content_type: Optional MIME type
            
        Returns:
            Unique identifier for the saved file
        """
        pass

    @abstractmethod
    async def get_file_data(
        self,
        file_identifier: str
    ) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """
        Retrieve file data and metadata.
        
        Args:
            file_identifier: Unique file identifier
            
        Returns:
            Tuple of (file_data, metadata) or None if not found
        """
        pass

    @abstractmethod
    async def delete_file(self, file_identifier: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            file_identifier: Unique file identifier
            
        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def file_exists(self, file_identifier: str) -> bool:
        """
        Check if a file exists.
        
        Args:
            file_identifier: Unique file identifier
            
        Returns:
            True if file exists
        """
        pass
