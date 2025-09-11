import numpy as np
from typing import Optional

from .reasoning_repository import ReasoningRepository


class MockReasoningRepository(ReasoningRepository):
    """
    Mock implementation of the reasoning repository for testing.
    Returns predefined analyses based on simple image and caption analysis.
    """
    
    def analyze(
        self, 
        image: np.ndarray, 
        segmentation_mask: np.ndarray, 
        caption: str,
        affected_percentage: Optional[float] = None
    ) -> str:
        """
        Generate a mock analysis based on image and caption.
        
        Args:
            image (np.ndarray): Original image as numpy array
            segmentation_mask (np.ndarray): Segmentation mask highlighting regions of interest
            caption (str): Caption describing the image
            affected_percentage (Optional[float]): Percentage of the plant affected by issues,
                calculated by the segmenter service
            
        Returns:
            str: Mock agricultural analysis
        """
        # Use provided affected_percentage or calculate it if not provided
        if affected_percentage is None:
            affected_percentage = np.mean(segmentation_mask > 0) * 100
        
        # Look for key terms in the caption
        analysis = ""
        
        # Determine severity based on affected percentage
        if affected_percentage > 30:
            severity = "severe"
        elif affected_percentage > 10:
            severity = "moderate"
        else:
            severity = "mild"
            
        # Check for common issues in the caption
        if "yellow" in caption.lower() or "chlorosis" in caption.lower():
            analysis = f"""Diagnosis: {severity.capitalize()} nitrogen deficiency
            
Symptoms: The plant is showing yellowish discoloration of leaves, particularly in older foliage. This classic sign of nitrogen deficiency affects approximately {affected_percentage:.1f}% of the plant.

Recommended Actions:
1. Apply nitrogen-rich fertilizer such as ammonium nitrate or urea
2. Consider a foliar spray for immediate uptake
3. Implement a regular fertilization schedule
4. Test soil pH, as very high or low pH can affect nitrogen availability"""

        elif "spots" in caption.lower() or "lesions" in caption.lower():
            analysis = f"""Diagnosis: {severity.capitalize()} fungal infection, likely Alternaria or Septoria leaf spot
            
Symptoms: The plant exhibits dark spots or lesions on approximately {affected_percentage:.1f}% of the foliage. These may enlarge and cause leaf drop if untreated.

Recommended Actions:
1. Remove and destroy affected leaves
2. Apply a copper-based fungicide or approved organic alternative
3. Improve air circulation around plants
4. Avoid overhead watering to reduce leaf moisture"""

        elif "wilting" in caption.lower() or "drooping" in caption.lower():
            analysis = f"""Diagnosis: {severity.capitalize()} water stress
            
Symptoms: The plant shows wilting or drooping affecting approximately {affected_percentage:.1f}% of the foliage, indicating potential water management issues.

Recommended Actions:
1. Check soil moisture at root level
2. Adjust irrigation schedule based on weather conditions
3. Add mulch to conserve soil moisture
4. If persistently wet, check for root rot issues and improve drainage"""

        else:
            # Generic analysis if no specific issues detected
            analysis = f"""Diagnosis: General plant stress of {severity} severity
            
Symptoms: The plant shows signs of stress affecting approximately {affected_percentage:.1f}% of the foliage, but the exact cause is unclear from the image alone.

Recommended Actions:
1. Monitor for changes in symptoms
2. Check soil nutrients with a comprehensive soil test
3. Ensure proper watering and light conditions
4. Inspect closely for signs of pests or disease"""

        return analysis 