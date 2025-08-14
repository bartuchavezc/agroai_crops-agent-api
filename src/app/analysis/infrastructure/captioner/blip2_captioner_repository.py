import numpy as np
from typing import Optional
import torch
from PIL import Image

from .captioner_repository import CaptionerRepository


class Blip2Repository(CaptionerRepository):
    """
    BLIP-2 implementation of the captioner repository.
    
    This class provides image captioning functionality using the BLIP-2 model.
    It supports two variants:
    1. Full BLIP-2 model (Salesforce/blip2-opt-2.7b)
    2. Lighter BLIP version for development environments
    """
    
    def __init__(
        self, 
        model_name: Optional[str] = None, 
        device: Optional[str] = None,
        max_new_tokens: Optional[int] = None,
        lightweight: Optional[bool] = None,
        lightweight_model_name: Optional[str] = None
    ):
        """
        Initialize the BLIP captioner.
        
        Args:
            model_name (Optional[str]): Name of the BLIP model to use
            device (Optional[str]): Device to run the model on ('cuda', 'cpu', etc.)
            max_new_tokens (Optional[int]): Maximum number of tokens to generate
            lightweight (Optional[bool]): Whether to use a lightweight model variant
            lightweight_model_name (Optional[str]): Name of the lightweight model variant
        """
        self.model_name = model_name
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.lightweight = lightweight
        self.lightweight_model_name = lightweight_model_name
        
        # Auto-switch to lightweight model if on CPU or if explicitly requested
        if self.lightweight or self.device == 'cpu':
            # Ensure lightweight_model_name is available if this logic is hit
            if self.lightweight_model_name:
                self.model_name = self.lightweight_model_name
            # else: log a warning or use a hardcoded default if appropriate, 
            # or rely on container to always provide it if lightweight is true.

        self.processor = None
        self.model = None
        
    def _load_model(self):
        """Load the BLIP model for inference"""
        try:
            # Import here to avoid loading dependencies if not needed
            if 'blip2' in self.model_name.lower():
                try:
                    from transformers import Blip2Processor, Blip2ForConditionalGeneration
                except ImportError:
                    print("Transformers package not found. Run 'poetry install' first.")
                    # Optional fallback or exit behavior
                self.processor = Blip2Processor.from_pretrained(self.model_name)
                self.model = Blip2ForConditionalGeneration.from_pretrained(
                    self.model_name, 
                    torch_dtype=torch.float16 if self.device == 'cuda' else torch.float32
                ).to(self.device)
            else:
                try:
                    from transformers import BlipProcessor, BlipForConditionalGeneration
                except ImportError:
                    print("Transformers package not found. Run 'poetry install' first.")
                    # Optional fallback or exit behavior
                self.processor = BlipProcessor.from_pretrained(self.model_name)
                self.model = BlipForConditionalGeneration.from_pretrained(self.model_name).to(self.device)
                
        except Exception as e:
            raise RuntimeError(f"Failed to load BLIP model: {str(e)}")
    
    def generate_caption(self, image: np.ndarray, segmentation_mask: Optional[np.ndarray] = None) -> str:
        """
        Generate a descriptive caption for the input image.
        
        Args:
            image (np.ndarray): Input image as numpy array
            segmentation_mask (Optional[np.ndarray]): Segmentation mask highlighting regions of interest
            
        Returns:
            str: Generated caption describing the image
        """
        # Load model if not already loaded
        if self.model is None:
            self._load_model()
        
        # Convert numpy array to PIL Image
        pil_image = Image.fromarray(image.astype('uint8'))
        
        # Apply segmentation mask if provided
        if segmentation_mask is not None:
            # Convert mask to boolean
            if segmentation_mask.dtype != bool:
                if len(segmentation_mask.shape) == 3 and segmentation_mask.shape[2] > 1:
                    # Multi-channel mask, use any non-zero values
                    bool_mask = np.any(segmentation_mask > 0, axis=2)
                else:
                    # Single-channel mask
                    bool_mask = segmentation_mask > 0
            else:
                bool_mask = segmentation_mask
                
            # Convert boolean mask to RGB for highlighting
            highlight_mask = np.zeros_like(image)
            highlight_mask[bool_mask] = [255, 0, 0]  # Red highlight
            
            # Apply alpha blending of original image and highlight
            alpha = 0.7  # 70% original, 30% highlight
            blended = (image * alpha + highlight_mask * (1 - alpha)).astype(np.uint8)
            pil_image = Image.fromarray(blended)
        
        # Process image and generate caption
        with torch.no_grad():
            inputs = self.processor(images=pil_image, return_tensors="pt").to(self.device)
            generated_ids = self.model.generate(
                **inputs, 
                max_new_tokens=self.max_new_tokens
            )
            caption = self.processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
        return caption