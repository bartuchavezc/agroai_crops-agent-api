import numpy as np
from typing import Optional

from .captioner_repository import CaptionerRepository


class MockCaptionerRepository(CaptionerRepository):
    """
    Mock implementation of the captioner repository for testing.
    Returns predefined captions based on simple image analysis.
    """
    
    def generate_caption(self, image: np.ndarray, segmentation_mask: Optional[np.ndarray] = None) -> str:
        """
        Generate a mock caption based on simple image analysis.
        
        Args:
            image (np.ndarray): Input image as numpy array
            segmentation_mask (Optional[np.ndarray]): Segmentation mask highlighting regions of interest
            
        Returns:
            str: Generated mock caption
        """
        # Calculate average color
        avg_color = np.mean(image, axis=(0, 1))
        
        # Determine if image is more green (plant-like)
        is_green_dominant = avg_color[1] > avg_color[0] and avg_color[1] > avg_color[2]
        
        # Analyze mask if provided
        if segmentation_mask is not None:
            mask_coverage = np.mean(segmentation_mask > 0)
            if mask_coverage > 0.3:
                affected_state = "severely affected"
            elif mask_coverage > 0.1:
                affected_state = "moderately affected"
            else:
                affected_state = "minimally affected"
        else:
            affected_state = "in unknown condition"
            
        # Generate caption based on analysis
        if is_green_dominant:
            return f"A green plant with leaves {affected_state}. The plant appears to be growing in a natural environment."
        else:
            return f"A crop plant {affected_state}. The image shows signs of potential nutrient deficiency or disease." 