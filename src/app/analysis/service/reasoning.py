"""
Reasoning service for crop analysis.
This service provides higher-level LLM reasoning functionality by using
repository implementations.
"""
import logging
import numpy as np

from ..infrastructure.llm_reasoning.reasoning_repository import ReasoningRepository
from ..domain.dto.segmentation_result import SegmentationResult
from src.app.utils.errors import ReasoningError


class ReasoningService:
    """
    Service for LLM reasoning in crop analysis.
    
    This service uses the repository pattern to abstract the underlying
    LLM implementation details. It focuses solely on generating reasoning
    and insights from text descriptions.
    """
    
    def __init__(self, repository: ReasoningRepository):
        """
        Initialize the reasoning service.
        
        Args:
            repository (ReasoningRepository): Reasoning repository implementation
                provided through dependency injection
        """
        self.repository = repository
        self.logger = logging.getLogger(__name__)
        
        # Get prompt template from config - REMOVED as we will call repo.analyze directly
        # config = ServicesConfig.get_llm_config()
        # self.prompt_template = config.get("prompt_template")
    
    def generate_reasoning(self, caption: str, affected_percentage: float) -> str:
        """
        Generate reasoning about a crop's health based on its description
        by calling the repository's analyze method, which should handle prompt formatting.
        
        Args:
            caption (str): Description of the crop image
            affected_percentage (float): Percentage of the plant affected by disease/stress
                
        Returns:
            str: Generated reasoning and analysis (expected to be a JSON string
                 from MistralRepository.analyze).
        """
        try:
            # Directly call the repository's analyze method.
            # The MistralRepository.analyze method is already set up to
            # create the detailed JSON prompt.
            # We pass None for image and segmentation_mask as the interface defines them
            # and MistralRepository.analyze uses caption and affected_percentage for its current prompt.
            # If other repositories needed image/mask here, this service would need to accept them.
            return self.repository.analyze(
                image=None,  # np.ndarray expected by interface
                segmentation_mask=None, # np.ndarray expected by interface
                caption=caption,
                affected_percentage=affected_percentage
            )
        except Exception as e:
            self.logger.error(f"Error generating reasoning: {str(e)}")
            raise ReasoningError(f"Failed to generate reasoning: {str(e)}")
    
    def analyze_crop(self, image: np.ndarray, segmentation_result: SegmentationResult, caption: str) -> str:
        """
        Analyze an image and generate agricultural insights.
        
        Args:
            image (np.ndarray): Original image as numpy array
            segmentation_result (SegmentationResult): Segmentation result DTO
            caption (str): Caption describing the image, from the captioner service
                
        Returns:
            str: Generated reasoning and analysis
        """
        try:
            # Extract affected percentage from segmentation result
            affected_percentage = segmentation_result.affected_percentage
            
            # Use the generate_reasoning method to create the analysis
            return self.generate_reasoning(caption, affected_percentage)
        except Exception as e:
            self.logger.error(f"Error analyzing crop: {str(e)}")
            raise ReasoningError(f"Failed to analyze crop: {str(e)}")
    

