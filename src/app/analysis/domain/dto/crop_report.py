from typing import List, Any, Optional, Dict
from dataclasses import dataclass


@dataclass
class CropReport:
    """
    Data Transfer Object for crop analysis report results.
    
    Attributes:
        caption (str): Text description of the crop image
        diagnosis (str): Analysis report with diagnostic information
        segmentation_mask (List[List[float]]): 2D segmentation mask as a nested list
        metadata (Optional[Dict[str, Any]]): Additional metadata about the analysis
    """
    caption: str
    diagnosis: str
    segmentation_mask: List[List[float]]
    metadata: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_dict(cls, data: dict) -> "CropReport":
        """
        Create a CropReport instance from a dictionary.
        
        Args:
            data (dict): Dictionary containing report data
            
        Returns:
            CropReport: Initialized CropReport instance
        """
        return cls(
            caption=data.get("caption", ""),
            diagnosis=data.get("diagnosis", ""),
            segmentation_mask=data.get("segmentation_mask", []),
            metadata=data.get("metadata", None)
        )
    
    def to_dict(self) -> dict:
        """
        Convert the CropReport to a dictionary.
        
        Returns:
            dict: Dictionary representation of the CropReport
        """
        return {
            "caption": self.caption,
            "diagnosis": self.diagnosis,
            "segmentation_mask": self.segmentation_mask,
            "metadata": self.metadata
        }
