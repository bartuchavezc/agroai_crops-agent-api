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







class InvalidInputError(CropAnalysisError):
    """Input is invalid or in wrong format."""
    status_code = 400
    error_code = "invalid_input"


class StorageError(CropAnalysisError):
    """Error related to file storage operations."""
    status_code = 500
    error_code = "storage_error"




class PermissionDeniedError(CropAnalysisError):
    """Your role does not allow this operation."""
    status_code = 403
    error_code = "permission_denied"


class RateLimitedError(CropAnalysisError):
    """Too many requests. Try again in a few minutes."""
    status_code = 429
    error_code = "rate_limited"

    def __init__(self, retry_after: int, message=None):
        super().__init__(message)
        self.retry_after = retry_after


class UserAlreadyExistsError(CropAnalysisError):
    """User already exists."""
    status_code = 400
    error_code = "user_already_exists"


class NotFoundError(CropAnalysisError):
    """Resource not found."""
    status_code = 404
    error_code = "not_found"


class ProviderKeyMissingError(CropAnalysisError):
    """No Gemini API key configured for this user. Add one in your profile."""
    status_code = 409
    error_code = "PROVIDER_KEY_MISSING"


class ProviderKeyInvalidError(CropAnalysisError):
    """The configured Gemini API key was rejected by the provider."""
    status_code = 409
    error_code = "PROVIDER_KEY_INVALID"


class ProviderQuotaExceededError(CropAnalysisError):
    """The Gemini API quota for this user's key is exhausted. Try again later."""
    status_code = 429
    error_code = "PROVIDER_QUOTA_EXCEEDED"


class ProviderError(CropAnalysisError):
    """The model provider returned an unexpected error."""
    status_code = 502
    error_code = "PROVIDER_ERROR"
