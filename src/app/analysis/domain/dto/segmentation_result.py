from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import numpy as np
from PIL import Image

@dataclass
class SegmentationResult:
    """
    Data Transfer Object for segmentation operation results.
    
    Attributes:
        segmentation_mask (List[List[float]]): 2D segmentation mask as a nested list
        affected_percentage (float): Percentage of the image affected by issues
        height (int): Height of the segmentation mask
        width (int): Width of the segmentation mask
        metadata (Dict[str, Any]): Additional metadata from the segmentation process
        overlay (Optional[Image.Image]): PIL Image with mask overlaid on original
    """
    segmentation_mask: List[List[float]]
    affected_percentage: float
    height: int
    width: int
    metadata: Optional[Dict[str, Any]] = None
    overlay: Optional[Image.Image] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> "SegmentationResult":
        """
        Create a SegmentationResult instance from a dictionary.
        
        Args:
            data (dict): Dictionary containing segmentation data
            
        Returns:
            SegmentationResult: Initialized SegmentationResult instance
        """
        return cls(
            segmentation_mask=data.get("segmentation_mask", []),
            affected_percentage=data.get("affected_percentage", 0.0),
            height=data.get("height", 0),
            width=data.get("width", 0),
            metadata=data.get("metadata"),
            overlay=data.get("overlay")
        )
    
    def to_dict(self) -> dict:
        """
        Convert the SegmentationResult to a dictionary.
        
        Returns:
            dict: Dictionary representation of the SegmentationResult
        """
        result = {
            "segmentation_mask": self.segmentation_mask,
            "affected_percentage": self.affected_percentage,
            "height": self.height,
            "width": self.width
        }
        
        if self.metadata:
            result["metadata"] = self.metadata
            
        return result
    
    @classmethod
    def from_numpy(cls, mask: np.ndarray, affected_percentage: float, metadata: Optional[Dict[str, Any]] = None, overlay: Optional[Image.Image] = None) -> "SegmentationResult":
        """
        Create a SegmentationResult from a numpy array mask.
        
        Args:
            mask (np.ndarray): Segmentation mask as numpy array
            affected_percentage (float): Percentage of the image affected by issues
            metadata (Optional[Dict[str, Any]]): Additional metadata
            overlay (Optional[Image.Image]): PIL Image with mask overlaid
            
        Returns:
            SegmentationResult: Initialized SegmentationResult instance
        """
        mask_list = mask.tolist() if isinstance(mask, np.ndarray) else mask
        
        return cls(
            segmentation_mask=mask_list,
            affected_percentage=affected_percentage,
            height=len(mask_list) if mask_list else 0,
            width=len(mask_list[0]) if mask_list and mask_list[0] else 0,
            metadata=metadata,
            overlay=overlay
        ) 