# src/shared/utils/errors.py
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


class AuthenticationError(CropAnalysisError):
    """Error related to authentication."""
    status_code = 401
    error_code = "authentication_error"


class AuthorizationError(CropAnalysisError):
    """Error related to authorization."""
    status_code = 403
    error_code = "authorization_error"


class UserAlreadyExistsError(CropAnalysisError):
    """User already exists."""
    status_code = 400
    error_code = "user_already_exists"


class QueueError(CropAnalysisError):
    """Error related to message queue operations."""
    status_code = 500
    error_code = "queue_error"


class SearchError(CropAnalysisError):
    """Error related to search operations."""
    status_code = 500
    error_code = "search_error"
