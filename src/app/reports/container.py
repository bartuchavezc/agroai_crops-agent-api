# reports/container.py 
from dependency_injector import containers, providers
# from src.app.database import AsyncSessionLocal # Removed
from src.app.database import get_db_session # Added
from .infrastructure.sql_reports_repository import SQLReportsRepository
from .service.reports_service import ReportsService
from .domain.repositories import ReportsRepository # Para el type hint

class ReportsContainer(containers.DeclarativeContainer):

    # No necesitamos wiring a módulos Flask aquí ya que la sesión se pasa directamente.
    # config = providers.Configuration() # Si necesitaras configuraciones específicas del módulo
    # Add a provider for the main application configuration
    app_config = providers.Configuration(name="app_config")

    # Proveedor de sesión de base de datos
    db_session_provider = providers.Resource(get_db_session) # Changed to Resource using get_db_session

    reports_repository: providers.Factory[ReportsRepository] = providers.Factory(
        SQLReportsRepository,
        session=db_session_provider, # Changed to use the Resource provider
    )

    reports_service = providers.Factory(
        ReportsService,
        reports_repository=reports_repository,
        config=app_config # Inject the main app_config here
    ) 