"""
Repository implementations for image captioning operations.
"""
from abc import ABC, abstractmethod
from PIL import Image

class CaptionerRepository(ABC):
    """
    Abstract base class defining the interface for image captioning operations.
    """
    
    @abstractmethod
    def generate_caption(self, image: Image.Image) -> str:
        """
        Generate a descriptive caption for the input image.
        
        Args:
            image (Image.Image): Input image
            
        Returns:
            str: Generated caption describing the image
        """
        pass
