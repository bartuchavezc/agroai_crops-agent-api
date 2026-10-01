"""
FastAPI application.

Layers:  providers (external data: weather)  <-  application (farm, reports, alerts, storage)
         <-  agent (Gemini BYOK, ADK runner, conversations, memory, diagnosis).  auth is transversal.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.admin.router import router as admin_router
from src.agent.conversations.router import router as chat_router
from src.agent.memory.router import router as memory_router
from src.agent.providers.router import router as provider_credentials_router
from src.agent.reasoning.router import layout_router
from src.agent.reasoning.router import router as analyze_router
from src.application.alerts.router import router as alerts_router
from src.application.farm.router import router as farm_router
from src.application.inventory.router import router as inventory_router
from src.application.irrigation.router import router as irrigation_router
from src.application.management.router import router as management_router
from src.application.notifications.router import router as notifications_router
from src.application.reports.router import router as reports_router
from src.application.satellite.router import router as satellite_router
from src.application.storage.router import router as upload_router
from src.auth.api.routes import router as auth_router
from src.config.bootstrap import build_container
from src.providers.weather.router import router as weather_router
from src.shared.database import dispose_database_connections, get_engine
from src.shared.utils import get_logger
from src.shared.utils.errors import CropAnalysisError

logger = get_logger(__name__)

API_PREFIX = "/api/v1"
ROUTERS = [
    auth_router,
    provider_credentials_router,
    layout_router,  # before farm_router: /fields/layout/extract must not be shadowed by /fields/{field_id}
    farm_router,
    reports_router,
    alerts_router,
    notifications_router,
    upload_router,
    weather_router,
    chat_router,
    memory_router,
    analyze_router,
    inventory_router,
    irrigation_router,
    management_router,
    satellite_router,
    admin_router,
]
WIRED_MODULES = [
    "src.auth.api.dependencies",
    "src.auth.api.routes",
    "src.agent.conversations.router",
    "src.agent.memory.router",
    "src.agent.providers.router",
    "src.agent.reasoning.router",
    "src.application.alerts.router",
    "src.application.farm.router",
    "src.application.notifications.router",
    "src.application.reports.router",
    "src.application.storage.router",
    "src.providers.weather.router",
    "src.application.inventory.router",
    "src.application.irrigation.router",
    "src.application.management.router",
    "src.application.satellite.router",
    "src.admin.router",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_database_connections()


def create_app() -> FastAPI:
    container = build_container()
    container.wire(modules=WIRED_MODULES)
    config = container.config

    # The interactive docs and the schema map every endpoint; only served in development.
    docs_enabled = bool(config.app.dev_mode())
    app = FastAPI(
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        title=config.app.name(),
        version=config.app.version(),
        description="AgroAI - asistente agronómico con Gemini (BYOK), memoria de agente y alertas SMN.",
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.container = container

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.app.cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(CropAnalysisError)
    async def domain_error_handler(request: Request, exc: CropAnalysisError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message, "error_code": exc.error_code},
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "An internal server error occurred."})

    @app.get("/health", tags=["Health"])
    async def health():
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    for router in ROUTERS:
        app.include_router(router, prefix=API_PREFIX)

    logger.info(f"{config.app.name()} v{config.app.version()} ready (dev_mode={config.app.dev_mode()})")
    return app


app = create_app()
