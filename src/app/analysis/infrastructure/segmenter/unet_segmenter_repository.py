"""
Repository implementations for image segmentation operations.
"""
import numpy as np
from typing import Dict, Any, Optional
import requests
from typing import Any
from PIL import Image
import io
import base64

from .segmenter_repository import SegmenterRepository


class UNetRepository(SegmenterRepository):
    """
    UNet-based implementation of the segmentation repository.
    
    This class provides segmentation functionality using a UNet model
    served via TorchServe.
    """
    
    def __init__(
        self, 
        model_endpoint: Optional[str] = None
    ):
        """
        Initialize the UNet segmenter.
        
        Args:
            model_endpoint (Optional[str]): TorchServe endpoint URL for the UNet model
        """
        # Configuration parameters are now directly passed and used
        self.model_endpoint = model_endpoint
    
    def _preprocess_image(self, image: np.ndarray) -> Any:
        """
        Preprocess the input image for UNet model.
        
        Args:
            image (np.ndarray): Input image
            
        Returns:
            np.ndarray: Preprocessed image array
        """
        # Convert to RGB if grayscale
        if len(image.shape) == 2 or image.shape[2] == 1:
            image = np.stack([image] * 3, axis=2)
        
        # Normalize to [0, 1]
        image = image.astype(np.float32) / 255.0
        
        return image
    
    def _postprocess_mask(self, mask: Any) -> np.ndarray:
        """
        Convert model output to segmentation mask.
        
        Args:
            mask (np.ndarray): Raw model output
            
        Returns:
            np.ndarray: Processed segmentation mask
        """
        # Assuming mask is [B, C, H, W] where C is number of classes
        # Convert to class indices
        if len(mask.shape) == 4 and mask.shape[1] > 1:
            mask = np.argmax(mask, axis=1)[0]  # Take first batch
        else:
            mask = (mask[0, 0] > 0.5).astype(np.float32)  # Binary threshold
            
        return mask
    
    def segment(self, image: np.ndarray):
        """
        Segment the input image using UNet via TorchServe.
        Args:
            image (np.ndarray): Input image as numpy array (H, W, C)
        Returns:
            Tuple[np.ndarray, Dict[str, Any]] or List[Tuple[np.ndarray, Dict[str, Any]]]: Segmentation mask(s) and metadata
        """
        return self._segment_torchserve(image)
    
    def _segment_torchserve(self, image: np.ndarray):
        """
        Perform segmentation using TorchServe endpoint.
        Args:
            image (np.ndarray): Input image
        Returns:
            Tuple[np.ndarray, Dict[str, Any]] or List[Tuple[np.ndarray, Dict[str, Any]]]: Segmentation mask(s) and metadata
        """
        pil_image = Image.fromarray(image.astype('uint8'))
        img_byte_arr = io.BytesIO()
        pil_image.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        try:
            response = requests.post(
                self.model_endpoint,
                files={"data": ("image.png", img_bytes, "image/png")}
            )
            if response.status_code != 200:
                raise RuntimeError(f"TorchServe request failed with status {response.status_code}: {response.text}")
            result = response.json()
            # Handle both single and batch results
            if isinstance(result, list):
                results = []
                for item in result:
                    mask_b64 = item.get("mask", "")
                    mask_bytes = base64.b64decode(mask_b64)
                    mask_img = Image.open(io.BytesIO(mask_bytes)).convert("L")
                    mask = np.array(mask_img, dtype=np.float32) / 255.0
                    metadata = {"has_disease": item.get("has_disease", None)}
                    results.append((mask, metadata))
                return results
            else:
                mask_b64 = result.get("mask", "")
                mask_bytes = base64.b64decode(mask_b64)
                mask_img = Image.open(io.BytesIO(mask_bytes)).convert("L")
                mask = np.array(mask_img, dtype=np.float32) / 255.0
                metadata = {"has_disease": result.get("has_disease", None)}
                return mask, metadata
        except Exception as e:
            raise RuntimeError(f"Error calling TorchServe endpoint: {str(e)}")
    
    def _calculate_metadata(self, mask: np.ndarray) -> Dict[str, Any]:
        """
        Calculate metadata from segmentation mask.
        
        Args:
            mask (np.ndarray): Segmentation mask
            
        Returns:
            Dict[str, Any]: Metadata including percentage of affected area
        """
        # Calculate percentage of affected area
        if len(mask.shape) == 2:
            total_pixels = mask.shape[0] * mask.shape[1]
            affected_pixels = np.sum(mask > 0)
            affected_percentage = (affected_pixels / total_pixels) * 100
        else:
            # Multi-class case
            total_pixels = mask.shape[0] * mask.shape[1]
            class_counts = {i: np.sum(mask == i) for i in range(np.max(mask) + 1)}
            affected_percentage = {
                f"class_{cls}": (count / total_pixels) * 100 
                for cls, count in class_counts.items() if cls > 0
            }
        
        return {
            "affected_percentage": affected_percentage,
            "height": mask.shape[0],
            "width": mask.shape[1]
        } 