import numpy as np
from typing import Optional
import requests
import io
from PIL import Image
import base64
import logging

from .captioner_repository import CaptionerRepository


class BlipContainerRepository(CaptionerRepository):
    """
    BLIP container implementation of the captioner repository.
    
    This class provides image captioning functionality by making HTTP calls
    to the containerized BLIP service rather than loading the model directly.
    """
    
    def __init__(
        self, 
        service_url: Optional[str] = None,
        timeout: Optional[int] = None
    ):
        """
        Initialize the BLIP container client.
        
        Args:
            service_url (Optional[str]): URL of the BLIP service
            timeout (Optional[int]): Request timeout in seconds
        """
        # Configuration parameters are now directly passed and used
        self.service_url = service_url if service_url is not None else "http://localhost:8000" # Default if not provided
        self.timeout = timeout if timeout is not None else 30 # Default if not provided
        
        # Endpoints
        self.caption_endpoint = f"{self.service_url}/caption"
        self.analyze_endpoint = f"{self.service_url}/analyze"
        self.health_endpoint = f"{self.service_url}/health"
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def check_health(self) -> bool:
        """
        Check if the BLIP service is healthy.
        
        Returns:
            bool: True if the service is healthy, False otherwise
        """
        try:
            response = requests.get(self.health_endpoint, timeout=self.timeout)
            return response.status_code == 200
        except Exception:
            return False
    
    def generate_caption(self, image: Image.Image) -> str:
        """
        Generate a descriptive caption for the input image by calling the BLIP service.
        
        Args:
            image (Image.Image): Input image
            
        Returns:
            str: Generated caption describing the image
        """
        try:
            # Ensure image is in RGB mode
            if image.mode != "RGB":
                image = image.convert("RGB")
                
            # Convert PIL image to bytes
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG')
            img_bytes = img_byte_arr.getvalue()
        
            # Create multipart form data with 'file' parameter (not 'image')
            files = {
                'file': ('image.jpg', img_bytes, 'image/jpeg')  # BLIP service expects 'file', not 'image'
            }
            
            response = requests.post(
                self.analyze_endpoint,
                files=files,
                timeout=self.timeout
            )

            if response.status_code != 200:
                raise RuntimeError(f"BLIP service returned error status: {response.status_code}")
            
            response_data = response.json()
            
            # Return the detailed description for agricultural analysis
            return response_data.get('detailed_description', 'No description generated')
            
        except Exception as e:
            self.logger.error(f"Failed to generate caption from BLIP service: {str(e)}")
            raise RuntimeError(f"Failed to generate caption from BLIP service: {str(e)}")
    
    def generate_basic_caption(self, image: np.ndarray) -> str:
        """
        Generate a simple caption for the input image.
        
        Args:
            image (np.ndarray): Input image as numpy array
            
        Returns:
            str: Generated basic caption
        """
        try:
            # Convert numpy array to PIL Image
            pil_image = Image.fromarray(image.astype('uint8'))
            
            # Ensure image is in RGB mode
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            
            # Convert PIL image to bytes
            img_byte_arr = io.BytesIO()
            pil_image.save(img_byte_arr, format='JPEG')
            img_byte_arr = img_byte_arr.getvalue()
            
            # Create multipart form data
            files = {
                'file': ('image.jpg', img_byte_arr, 'image/jpeg')
            }
            
            # Use the basic caption endpoint
            response = requests.post(
                self.caption_endpoint,
                files=files,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                raise RuntimeError(f"BLIP service returned error status: {response.status_code}")
            
            response_data = response.json()
            
            # Return the simple caption
            return response_data.get('caption', 'No caption generated')
            
        except Exception as e:
            self.logger.error(f"Failed to generate caption from BLIP service: {str(e)}")
            raise RuntimeError(f"Failed to generate caption from BLIP service: {str(e)}") 