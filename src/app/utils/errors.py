"""
Custom exception classes for the application.
"""

class CropAnalysisError(Exception):
    """Base exception class for all crop analysis errors."""
    status_code = 500
    error_code = "crop_analysis_error"
    
    def __init__(self, message=None, status_code=None, error_code=None):
        self.message = message or self.__class__.__doc__
        self.status_code = status_code or self.__class__.status_code
        self.error_code = error_code or self.__class__.error_code
        super().__init__(self.message)


class ImagePreprocessingError(CropAnalysisError):
    """Error during image preprocessing."""
    status_code = 400
    error_code = "preprocessing_error"


class SegmentationError(CropAnalysisError):
    """Error during image segmentation."""
    status_code = 500
    error_code = "segmentation_error"


class CaptioningError(CropAnalysisError):
    """Error during image captioning."""
    status_code = 500
    error_code = "captioning_error"


class ReasoningError(CropAnalysisError):
    """Error during crop analysis reasoning."""
    status_code = 500
    error_code = "reasoning_error"


class MissingInputError(CropAnalysisError):
    """Required input is missing."""
    status_code = 400
    error_code = "missing_input"


class InvalidInputError(CropAnalysisError):
    """Input is invalid or in wrong format."""
    status_code = 400
    error_code = "invalid_input"


class StorageError(CropAnalysisError):
    """Error related to file storage operations."""
    status_code = 500
    error_code = "storage_error"