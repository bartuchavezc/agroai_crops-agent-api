"""
FastAPI application initialization.
"""
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import configure_mappers
from src.api import api_v1_router, auth_router
from src.app.config.core import load_app_config
from src.app.container import Container
from src.app.database import init_database_connections, init_db_tables
from src.app.timeseries import init_timescale_connections, init_timescale_tables
from src.app.utils.errors import CropAnalysisError
from src.app.utils.logger import get_logger


container = Container()
resolved_config = load_app_config()
container.config.from_dict(resolved_config)


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

db_config = container.config.database() 

db_url = db_config.get("url")
db_echo = db_config.get("echo", False)

if not db_url:
    sys.stderr.write("CRITICAL: DATABASE_URL not found in configuration. Application cannot start.\n")
    raise ValueError("DATABASE_URL is not configured.")
init_database_connections(db_url=db_url, echo_sql=db_echo)

ts_config = container.config.timescale()

ts_url = ts_config.get("url")
ts_echo = ts_config.get("echo", False)

if not ts_url:
    sys.stderr.write("CRITICAL: TIMESCALE_URL not found in configuration. Application cannot start.\n")
    raise ValueError("TIMESCALE_URL is not configured.")
init_timescale_connections(timescale_url=ts_url, echo_sql=ts_echo)

logger = get_logger(__name__)

def create_app(app_container: Container) -> FastAPI:
    configure_mappers()

    app = FastAPI(
        title=app_container.config.app.name(),
        version=app_container.config.app.version(),
        description="API for analyzing crop images to detect nutrient deficiencies and diseases.",
        redirect_slashes=False  # Disable automatic trailing slash redirects
    )
    app.state.container = app_container

    # Database table initialization on startup
    @app.on_event("startup")
    async def startup_event():
        logger.info("Initializing database tables...")
        try:
            await init_db_tables()
            await init_timescale_tables()
            logger.info("Database table initialization complete.")
        except Exception as e:
            logger.error(f"Failed to initialize database tables: {e}")
            raise

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception for request {request.method} {request.url}: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})



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

    origins = app_container.config.app.cors_origins()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    
    async def health_check():
        """Simple health check endpoint."""
        return {"status": "ok"}
    
    app.add_api_route("/health", health_check, methods=["GET"], summary="Health Check", description="Simple health check endpoint.", tags=["Health"])

    app.include_router(api_v1_router, prefix="/api")
    app.include_router(auth_router, prefix="/api/v1")

    logger.info(f"{app_container.config.app.name()} application created successfully. Dev Mode: {app_container.config.app.dev_mode()}")
    if app_container.config.storage.base_data_path(): 
        logger.info(f"Storage base path: {app_container.config.storage.base_data_path()}")
    return app

# --- Create App Instance for Uvicorn ---
app = create_app(container)