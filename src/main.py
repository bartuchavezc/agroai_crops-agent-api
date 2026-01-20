# src/main.py
"""
FastAPI application initialization - New Architecture.

This is the new entry point using the 3-layer architecture:
- Auth: Authentication and user management
- Ingestion: Data reception, queues, managers
- Agent: Conversational AI, search, reasoning
- Action: Reports, storage, alerts
"""
import sys
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import configure_mappers

from src.config.settings import load_app_config
from src.config.container import Container
from src.shared.database import init_database_connections, init_db_tables
from src.shared.database.timescale import init_timescale_connections, init_timescale_tables
from src.shared.utils.errors import CropAnalysisError
from src.shared.utils import get_logger

# Import routers from new layers
from src.auth.api import auth_router
from src.ingestion.reception.api import weather_router, upload_router
from src.agent.api import chat_router
from src.action.api import reports_router, alerts_router, analyze_router

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application
    """
    # Initialize container and load configuration
    container = Container()
    resolved_config = load_app_config()
    container.config.from_dict(resolved_config)
    
    # Wire container to modules
    container.wire(modules=[
        # Auth layer
        'src.auth.api.routes',
        'src.auth.api.dependencies',
        # Ingestion layer
        'src.ingestion.reception.api.weather_router',
        'src.ingestion.reception.api.upload_router',
        # Agent layer
        'src.agent.api.chat_router',
        # Action layer
        'src.action.api.reports_router',
        'src.action.api.alerts_router',
        'src.action.api.analyze_router',
    ])
    
    # Initialize database connections
    _init_databases(container)
    
    # Configure SQLAlchemy mappers
    configure_mappers()
    
    # Create FastAPI app
    app = FastAPI(
        title=container.config.app.name(),
        version=container.config.app.version(),
        description="AgroAI Crops Agent API - Agricultural Intelligence Platform",
        redirect_slashes=False,
    )
    
    # Store container in app state
    app.state.container = container
    
    # Register startup/shutdown events
    _register_events(app)
    
    # Register exception handlers
    _register_exception_handlers(app)
    
    # Configure CORS
    _configure_cors(app, container)
    
    # Register routes
    _register_routes(app)
    
    logger.info(
        f"{container.config.app.name()} v{container.config.app.version()} created. "
        f"Dev Mode: {container.config.app.dev_mode()}"
    )
    
    return app


def _init_databases(container: Container) -> None:
    """Initialize database connections."""
    # PostgreSQL
    db_config = container.config.database()
    db_url = db_config.get("url")
    db_echo = db_config.get("echo", False)
    
    if not db_url:
        sys.stderr.write("CRITICAL: DATABASE_URL not configured.\n")
        raise ValueError("DATABASE_URL is not configured.")
    
    init_database_connections(db_url=db_url, echo_sql=db_echo)
    
    # TimescaleDB
    ts_config = container.config.timescale()
    ts_url = ts_config.get("url")
    ts_echo = ts_config.get("echo", False)
    
    if not ts_url:
        sys.stderr.write("CRITICAL: TIMESCALE_URL not configured.\n")
        raise ValueError("TIMESCALE_URL is not configured.")
    
    init_timescale_connections(timescale_url=ts_url, echo_sql=ts_echo)


def _register_events(app: FastAPI) -> None:
    """Register startup and shutdown events."""
    
    @app.on_event("startup")
    async def startup_event():
        logger.info("Starting application...")
        try:
            await init_db_tables()
            await init_timescale_tables()
            logger.info("Database tables initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize database tables: {e}")
            raise
    
    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("Shutting down application...")
        # Close queue connections if needed
        container = app.state.container
        try:
            queue = container.ingestion.message_queue()
            await queue.close()
        except Exception:
            pass


def _register_exception_handlers(app: FastAPI) -> None:
    """Register exception handlers."""
    
    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error(
            f"Unhandled exception for {request.method} {request.url}: {exc}",
            exc_info=True
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."}
        )
    
    @app.exception_handler(CropAnalysisError)
    async def crop_analysis_exception_handler(request: Request, exc: CropAnalysisError):
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


def _configure_cors(app: FastAPI, container: Container) -> None:
    """Configure CORS middleware."""
    origins = container.config.app.cors_origins()
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _register_routes(app: FastAPI) -> None:
    """Register API routes."""
    
    # Health check
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "ok"}
    
    # API v1 routes
    api_prefix = "/api/v1"
    
    # Auth routes
    app.include_router(auth_router, prefix=api_prefix)
    
    # Ingestion routes
    app.include_router(weather_router, prefix=api_prefix)
    app.include_router(upload_router, prefix=api_prefix)
    
    # Agent routes
    app.include_router(chat_router, prefix=api_prefix)
    
    # Action routes
    app.include_router(reports_router, prefix=api_prefix)
    app.include_router(alerts_router, prefix=api_prefix)
    app.include_router(analyze_router, prefix=api_prefix)


# Create app instance for Uvicorn
app = create_app()
