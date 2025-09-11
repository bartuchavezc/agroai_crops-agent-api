import numpy as np
from typing import Dict, Any, Tuple
from datetime import datetime

from .segmenter_repository import SegmenterRepository


class MockSegmenterRepository(SegmenterRepository):
    """
    Mock implementation of the segmenter repository for testing.
    Returns predefined segmentation masks based on simple image analysis.
    """
    
    def segment(self, image: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Generate a mock segmentation mask based on simple image analysis.
        
        Args:
            image (np.ndarray): Input image as numpy array
            
        Returns:
            Tuple[np.ndarray, Dict[str, Any]]: Mock segmentation mask and metadata
        """
        # Generate a simple binary mask for testing
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        mask[100:200, 100:200] = 1  # Create a small square in the center
        
        # Create metadata dictionary
        metadata = {
            "width": image.shape[1],
            "height": image.shape[0],
            "format": "png",
            "timestamp": datetime.now().isoformat()
        }
        
        return mask, metadata