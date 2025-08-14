"""
Repository implementations for image segmentation operations.
"""
import numpy as np
from typing import Dict, Any, Optional, Tuple
import requests
import json
from typing import Any
from PIL import Image
import io
import base64

from .segmenter_repository import SegmenterRepository


class UNetRepository(SegmenterRepository):
    """
    UNet-based implementation of the segmentation repository.
    
    This class provides segmentation functionality using a UNet model
    served via TorchServe or loaded locally.
    """
    
    def __init__(
        self, 
        model_endpoint: Optional[str] = None, 
        local_model_path: Optional[str] = None,
        device: Optional[str] = None
    ):
        """
        Initialize the UNet segmenter.
        
        Args:
            model_endpoint (Optional[str]): TorchServe endpoint URL for the UNet model
            local_model_path (Optional[str]): Path to local model weights if not using TorchServe
            device (Optional[str]): Device to run the model on ('cuda', 'cpu')
        """
        # Configuration parameters are now directly passed and used
        self.model_endpoint = model_endpoint
        self.local_model_path = local_model_path
        self.device = device
        self.model = None
        
        # Load local model if specified
        if self.local_model_path:
            self._load_local_model()
    
    def _load_local_model(self):
        """Load UNet model locally (for development or standalone operation)"""
        try:
            import torch  # Defer import to avoid loading CUDA when not needed
            self.model = torch.load(self.local_model_path, map_location=self.device)
            self.model.eval()
        except Exception as e:
            raise RuntimeError(f"Failed to load local UNet model: {str(e)}")
    
    def _preprocess_image(self, image: np.ndarray) -> Any:
        """
        Preprocess the input image for UNet model.
        
        Args:
            image (np.ndarray): Input image
            
        Returns:
            torch.Tensor: Preprocessed image tensor
        """
        # Convert to RGB if grayscale
        if len(image.shape) == 2 or image.shape[2] == 1:
            image = np.stack([image] * 3, axis=2)
        
        # Normalize to [0, 1]
        image = image.astype(np.float32) / 255.0
        
        # Convert to tensor and add batch dimension
        import torch  # Defer import
        tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0)
        return tensor.to(self.device)
    
    def _postprocess_mask(self, mask: Any) -> np.ndarray:
        """
        Convert model output to segmentation mask.
        
        Args:
            mask (torch.Tensor): Raw model output
            
        Returns:
            np.ndarray: Processed segmentation mask
        """
        try:
            import torch  # Defer import
            torch_tensor = torch.Tensor
        except Exception:
            torch_tensor = tuple()  # type: ignore

        if isinstance(mask, torch_tensor):
            mask = mask.detach().cpu().numpy()
        
        # Assuming mask is [B, C, H, W] where C is number of classes
        # Convert to class indices
        if len(mask.shape) == 4 and mask.shape[1] > 1:
            mask = np.argmax(mask, axis=1)[0]  # Take first batch
        else:
            mask = (mask[0, 0] > 0.5).astype(np.float32)  # Binary threshold
            
        return mask
    
    def segment(self, image: np.ndarray):
        """
        Segment the input image using UNet.
        Args:
            image (np.ndarray): Input image as numpy array (H, W, C)
        Returns:
            Tuple[np.ndarray, Dict[str, Any]] or List[Tuple[np.ndarray, Dict[str, Any]]]: Segmentation mask(s) and metadata
        """
        if self.model is not None:
            return self._segment_local(image)
        else:
            result = self._segment_torchserve(image)
            return result
    
    def _segment_local(self, image: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Perform segmentation using local model.
        
        Args:
            image (np.ndarray): Input image
            
        Returns:
            Tuple[np.ndarray, Dict[str, Any]]: Segmentation mask and metadata
        """
        if self.model is None:
            raise RuntimeError("Local model not loaded")
        
        import torch  # Defer import
        with torch.no_grad():
            tensor = self._preprocess_image(image)
            output = self.model(tensor)
            mask = self._postprocess_mask(output)
            
        # Calculate metadata (e.g., percentage of affected area)
        metadata = self._calculate_metadata(mask)
        
        return mask, metadata
    
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