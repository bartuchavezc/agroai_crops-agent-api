"""
Captioner service for crop image analysis.
This service provides higher-level captioning functionality by using
repository implementations.
"""
import numpy as np
import logging
from typing import Optional
from PIL import Image
from ..infrastructure.captioner.captioner_repository import CaptionerRepository
from src.app.utils.errors import CaptioningError


class CaptionerService:
    """
    Service for image captioning operations in crop analysis.
    
    This service uses the repository pattern to abstract the underlying
    captioning implementation details. It focuses solely on generating
    captions for images.
    """
    
    def __init__(self, repository: CaptionerRepository):
        """
        Initialize the captioner service.
        
        Args:
            repository (CaptionerRepository): Captioning repository implementation
                provided through dependency injection
        """
        self.repository = repository
        self.logger = logging.getLogger(__name__)
    
    def generate_caption(self, image: Image.Image) -> str:
        """
        Generate a caption for the given image.
        
        Args:
            image (Image.Image): Input image
                
        Returns:
            str: Generated caption
        """
        try:
            return self.repository.generate_caption(image)
        except Exception as e:
            self.logger.error(f"Error generating caption: {str(e)}")
            raise CaptioningError(f"Failed to generate caption: {str(e)}")
