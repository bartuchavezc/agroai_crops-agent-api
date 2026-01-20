# src/action/storage/local_adapter.py
"""
Local filesystem storage adapter.
"""
import os
import json
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from datetime import datetime

from .interfaces import FileRepository

logger = logging.getLogger(__name__)


class LocalFileRepository(FileRepository):
    """
    Local filesystem implementation of file repository.
    
    Stores files in a configured directory with metadata in JSON sidecars.
    """
    
    def __init__(self, base_path: str):
        """
        Initialize local file repository.
        
        Args:
            base_path: Base directory for file storage
        """
        self.base_path = Path(base_path)
        self._ensure_directory()
        logger.info(f"LocalFileRepository initialized at: {self.base_path}")
    
    def _ensure_directory(self) -> None:
        """Ensure the storage directory exists."""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            logger.warning(f"Could not create directory {self.base_path}: {e}")
    
    def _generate_identifier(self, file_name: str) -> str:
        """Generate a unique file identifier."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        # Get extension from original filename
        ext = ""
        if file_name and "." in file_name:
            ext = "." + file_name.rsplit(".", 1)[-1].lower()
        
        return f"{timestamp}_{unique_id}{ext}"
    
    def _get_file_path(self, identifier: str) -> Path:
        """Get full path for a file identifier."""
        return self.base_path / identifier
    
    def _get_metadata_path(self, identifier: str) -> Path:
        """Get metadata file path for an identifier."""
        return self.base_path / f"{identifier}.meta.json"
    
    async def save_file(
        self,
        file_name: str,
        file_data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        """Save file to local storage."""
        identifier = self._generate_identifier(file_name)
        file_path = self._get_file_path(identifier)
        metadata_path = self._get_metadata_path(identifier)
        
        # Save file data
        with open(file_path, "wb") as f:
            f.write(file_data)
        
        # Save metadata
        metadata = {
            "original_name": file_name,
            "content_type": content_type,
            "size": len(file_data),
            "created_at": datetime.utcnow().isoformat(),
        }
        
        with open(metadata_path, "w") as f:
            json.dump(metadata, f)
        
        logger.debug(f"Saved file: {identifier}")
        return identifier
    
    async def get_file_data(
        self,
        file_identifier: str
    ) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        """Retrieve file data and metadata."""
        file_path = self._get_file_path(file_identifier)
        metadata_path = self._get_metadata_path(file_identifier)
        
        if not file_path.exists():
            return None
        
        # Read file data
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        # Read metadata
        metadata = {}
        if metadata_path.exists():
            with open(metadata_path, "r") as f:
                metadata = json.load(f)
        
        return file_data, metadata
    
    async def delete_file(self, file_identifier: str) -> bool:
        """Delete file from storage."""
        file_path = self._get_file_path(file_identifier)
        metadata_path = self._get_metadata_path(file_identifier)
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            if metadata_path.exists():
                metadata_path.unlink()
            return True
        except Exception as e:
            logger.error(f"Error deleting file {file_identifier}: {e}")
            return False
    
    async def file_exists(self, file_identifier: str) -> bool:
        """Check if file exists."""
        return self._get_file_path(file_identifier).exists()
