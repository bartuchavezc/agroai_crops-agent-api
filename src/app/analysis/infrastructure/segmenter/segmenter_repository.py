"""
Repository for image segmentation operations.
"""
from abc import ABC, abstractmethod
import numpy as np
from typing import Dict, Any, Tuple


class SegmenterRepository(ABC):
    """
    Abstract base class defining the interface for segmentation operations.
    """
    
    @abstractmethod
    def segment(self, image: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Segment an image to identify plant regions and potential disease areas.
        
        Args:
            image (np.ndarray): Input image as numpy array
            
        Returns:
            Tuple[np.ndarray, Dict[str, Any]]: Segmentation mask and metadata
        """
        pass