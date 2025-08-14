"""
FastAPI application initialization.
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
from sqlalchemy.orm import configure_mappers
# Removed: import yaml, from pathlib import Path, import logging
# These are now handled in src.app.config.core

from src.app.container import Container # Main container
from src.api import api_v1_router, auth_router
from src.app.utils.errors import CropAnalysisError
from src.app.database import init_database_connections, init_db_tables
from src.app.timeseries import init_timescale_connections, init_timescale_tables
from src.app.config.core import load_app_config # Import the centralized config loader
from src.app.utils.logger import get_logger # Moved up, will be initialized after container

# --- Container Initialization and Wiring ---
# 1. Create and configure the main container
container = Container()
resolved_config = load_app_config()
container.config.from_dict(resolved_config)

# 2. Wire the container to all necessary modules
container.wire(modules=[
    'src.api.routes.analyze_router',
    'src.api.routes.chat_router',
    'src.api.routes.reports_router',
    'src.api.routes.upload_router',
    'src.api.routes.user_router',
    'src.api.routes.auth_router',
    'src.api.routes.weather_zones',
    'src.api.routes.weather_data_router',
    'src.api.farm_management.account_router',
    'src.api.farm_management.field_router',
    'src.api.farm_management.crop_master_router',
    'src.api.farm_management.crop_cycle_router',
    'src.api.farm_management.report_campaign_router',
    'src.api.__init__',
    'src.app.users.service.user_service',
    'src.app.analysis.service.segmenter',
    'src.app.analysis.service.captioner',
    'src.app.analysis.service.reasoning',
    'src.app.reports.service.reports_service',
    'src.app.storage.service.storage_service',
    'src.app.weather_zones.service.zone_management',
])

# --- Database Initialization (needs config from container) ---
db_config = container.config.database() # This returns a Configuration subsection or dict

# Access nested config values as dictionary items or with .get() for safety
db_url = db_config.get("url") # Changed from db_config.url()
db_echo = db_config.get("echo", False) # Changed from db_config.echo(), added default

if not db_url:
    sys.stderr.write("CRITICAL: DATABASE_URL not found in configuration. Application cannot start.\n")
    raise ValueError("DATABASE_URL is not configured.")
init_database_connections(db_url=db_url, echo_sql=db_echo)

# --- TimescaleDB Initialization (needs config from container) ---
ts_config = container.config.timescale() # This returns a Configuration subsection or dict

# Access nested config values as dictionary items or with .get() for safety
ts_url = ts_config.get("url") # Changed from ts_config.url()
ts_echo = ts_config.get("echo", False) # Changed from ts_config.echo(), added default

if not ts_url:
    sys.stderr.write("CRITICAL: TIMESCALEDB_URL not found in configuration. Application cannot start.\n")
    raise ValueError("TIMESCALEDB_URL is not configured.")
init_timescale_connections(timescale_url=ts_url, echo_sql=ts_echo)

# --- Logger Initialization (can use container config) ---
logger = get_logger(__name__) # Initialize logger after container and config

# --- FastAPI App Creation Function ---
def create_app(app_container: Container) -> FastAPI: # RENAMED from create_app_instance
    # Ensure all SQLAlchemy models are configured before the app starts serving requests.
    # This is crucial for resolving string-based relationships after all modules are loaded.
    configure_mappers()

    app = FastAPI(
        title=app_container.config.app.name(),
        version=app_container.config.app.version(),
        description="API for analyzing crop images to detect nutrient deficiencies and diseases.",
        redirect_slashes=False  # Disable automatic trailing slash redirects
    )
    app.state.container = app_container # Store the single, wired container

    # Generic Exception Handler
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception for request {request.method} {request.url}: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})

    @app.on_event("startup")
    async def on_startup():
        logger.info("Initializing database tables...")
        await init_db_tables() # Uses global _async_engine
        await init_timescale_tables() # Uses global _async_engine
        logger.info("Database table initialization complete.")

    @app.exception_handler(CropAnalysisError)
    async def custom_crop_analysis_exception_handler(request: Request, exc: CropAnalysisError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "status": "error",
                "error": str(exc),
                "error_code": exc.error_code,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    origins = app_container.config.app.cors_origins() # Use wired container for config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    app.include_router(api_v1_router, prefix="/api") # api_v1_router now imports modules that should be wired
    app.include_router(auth_router, prefix="/api/v1") # Mount auth endpoints outside the protected router

    logger.info(f"{app_container.config.app.name()} application created successfully. Dev Mode: {app_container.config.app.dev_mode()}")
    if app_container.config.storage.base_data_path(): 
        logger.info(f"Storage base path: {app_container.config.storage.base_data_path()}")
    return app

# --- Create App Instance for Uvicorn ---
app = create_app(container) # CALLING the renamed function 