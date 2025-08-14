from fastapi import APIRouter

from . import account_router
from . import field_router
from . import crop_master_router
from . import crop_cycle_router
from . import report_campaign_router

# Main router for the /farm-management path prefix
router = APIRouter(
    prefix="/farm-management", # This sets the base path for all included routers
    tags=["Farm Management"], # A general tag for this module
    redirect_slashes=False  # Disable trailing slash redirects
)

# Include individual entity routers
# Their paths will be relative to the prefix defined above.
# For example, account_router paths like "/accounts/" will become "/farm-management/accounts/"
router.include_router(account_router.router)
router.include_router(field_router.router)
router.include_router(crop_master_router.router)
router.include_router(crop_cycle_router.router)
router.include_router(report_campaign_router.router)

__all__ = ["router"] # Export the main router for this module 