"""
API router package for FastAPI.
"""
from fastapi import APIRouter, Depends

from .routes.analyze_router import router as analyze_router
from .routes.chat_router import router as chat_router
from .routes.reports_router import router as reports_router
from .routes.upload_router import router as upload_router
from .routes.user_router import router as user_router
from .routes.weather_zones import router as weather_zones_router
from .routes.weather_data_router import router as weather_data_router
from .farm_management import router as farm_management_router
from src.app.auth.infrastructure.auth_dependencies import get_current_user

# Main router for the /v1 path prefix
api_v1_router = APIRouter(
    prefix="/v1", # This sets the base path for all included routers
    tags=["API v1"], # A general tag for this module
    redirect_slashes=False,  # Disable trailing slash redirects
    dependencies=[Depends(get_current_user)] # Protección global
)

# Include individual module routers (protected)
api_v1_router.include_router(farm_management_router)
api_v1_router.include_router(analyze_router)
api_v1_router.include_router(chat_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(upload_router)
api_v1_router.include_router(user_router)
api_v1_router.include_router(weather_zones_router)
api_v1_router.include_router(weather_data_router)

# Import auth_router for direct mounting in the FastAPI app
from .routes.auth_router import auth_router

__all__ = ["api_v1_router", "auth_router"]

# The commented out HTTPException handler is generally handled by FastAPI by default. 