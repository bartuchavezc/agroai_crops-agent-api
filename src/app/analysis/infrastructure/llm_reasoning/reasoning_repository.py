"""
Repository implementations for agricultural reasoning operations using LLMs.
"""
from abc import ABC, abstractmethod
import numpy as np
from typing import Optional

class ReasoningRepository(ABC):
    """
    Abstract base class defining the interface for reasoning operations.
    """
    
    @abstractmethod
    def generate_from_prompt(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Generate a response from the LLM using the provided prompt.
        
        Args:
            prompt (str): The complete prompt for the LLM
            system_prompt (Optional[str]): Optional system prompt to guide the LLM
            
        Returns:
            str: Generated response from the LLM
        """
        pass
    
    @abstractmethod
    def analyze(
        self, 
        image: np.ndarray, 
        segmentation_mask: np.ndarray, 
        caption: str,
        affected_percentage: Optional[float] = None
    ) -> str:
        """
        Analyze an image using the caption and segmentation mask to generate
        agricultural insights.
        
        Args:
            image (np.ndarray): Original image as numpy array
            segmentation_mask (np.ndarray): Segmentation mask highlighting regions of interest
            caption (str): Caption describing the image, from the captioner service
            affected_percentage (Optional[float]): Percentage of the plant affected by issues,
                calculated by the segmenter service
            
        Returns:
            str: Agricultural analysis and diagnostic text
        """
        pass



