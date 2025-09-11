"""
Segmenter service for crop image analysis.
This service provides higher-level segmentation functionality by using
repository implementations.
"""
import numpy as np
import logging
from typing import Dict, Union
from PIL import Image

from ..infrastructure.segmenter.segmenter_repository import SegmenterRepository
from ..domain.dto.segmentation_result import SegmentationResult
from src.app.utils.errors import SegmentationError


class SegmenterService:
    """
    Service for image segmentation operations in crop analysis.
    
    This service uses the repository pattern to abstract the underlying
    segmentation implementation details. It focuses solely on image segmentation
    and related analysis.
    """
    
    def __init__(self, repository: SegmenterRepository):
        """
        Initialize the segmenter service.
        
        Args:
            repository (SegmenterRepository): Segmentation repository implementation
                provided through dependency injection
        """
        self.repository = repository
        self.logger = logging.getLogger(__name__)
    
    def segment_image(self, image: Image.Image) -> SegmentationResult:
        """
        Segment an image to identify plant and disease regions.
        
        Args:
            image (Image.Image): Input image as PIL image
            
        Returns:
            SegmentationResult: Data transfer object with segmentation results
            
        Raises:
            SegmentationError: If segmentation fails
        """
        try:
            # Get raw segmentation results from repository
            mask, metadata = self.repository.segment(np.array(image))
            
            # Calculate affected percentage
            affected_percentage = self.analyze_damage_percentage(mask)
            
            # Convert numpy mask for overlaying
            overlay = self.overlay_mask(image, mask)

            # For multi-class masks, use the total affected percentage
            if isinstance(affected_percentage, dict):
                total_affected = sum(affected_percentage.values())
            else:
                total_affected = affected_percentage
            
            # Create and return a DTO with the results
            return SegmentationResult.from_numpy(
                mask=mask,
                overlay=overlay,
                affected_percentage=total_affected,
                metadata=metadata
            )
        except Exception as e:
            self.logger.error(f"Segmentation failed: {str(e)}")
            raise SegmentationError(f"Failed to segment image: {str(e)}") from e
    
    def analyze_damage_percentage(self, mask: np.ndarray) -> Union[float, Dict[str, float]]:
        """
        Calculate damage percentage from segmentation mask.
        
        Args:
            mask (np.ndarray): Segmentation mask
            
        Returns:
            Union[float, Dict[str, float]]: Percentage of damage or class-wise percentages
        """
        try:
            if len(mask.shape) == 2:
                # Binary mask
                total_pixels = mask.shape[0] * mask.shape[1]
                affected_pixels = np.sum(mask > 0)
                return (affected_pixels / total_pixels) * 100
            else:
                # Multi-class mask
                total_pixels = mask.shape[0] * mask.shape[1]
                class_counts = {i: np.sum(mask == i) for i in range(np.max(mask) + 1)}
                return {
                    f"class_{cls}": (count / total_pixels) * 100 
                    for cls, count in class_counts.items() if cls > 0
                }
        except Exception as e:
            self.logger.error(f"Damage percentage calculation failed: {str(e)}")
            raise SegmentationError(f"Failed to calculate damage percentage: {str(e)}") from e

    def overlay_mask(self, original_img: Image.Image, mask_array: np.ndarray, color=(255, 0, 0), alpha=0.5):
        """
        Overlays a binary mask onto the original image with proper dimension handling.
        
        Args:
            original_img: PIL.Image - The original image to overlay the mask on
            mask_array: np.ndarray - The mask array (H, W)
            color: tuple - RGB color to use for the overlay (default: red)
            alpha: float - Transparency factor (0-1) for the overlay
            
        Returns:
            PIL.Image - The original image with the mask overlaid
        """
        try:
            mask = mask_array
                
            if mask.max() <= 1.0:
                mask = (mask * 255).astype('uint8')
            else:
                mask = mask.astype('uint8')

            mask_img = Image.fromarray(mask).convert("L")
            
            if mask_img.size != original_img.size:
                self.logger.warning(
                    f"Mask dimensions {mask_img.size} don't match image dimensions {original_img.size}, resizing mask"
                )
                mask_img = mask_img.resize(original_img.size, Image.LANCZOS)
            
            overlay = Image.new("RGB", original_img.size, color)
            
            composite = Image.composite(overlay, original_img, mask_img)

            return Image.blend(original_img, composite, alpha)
            
        except Exception as e:
            self.logger.error(f"Error overlaying mask: {str(e)}")
            return original_img