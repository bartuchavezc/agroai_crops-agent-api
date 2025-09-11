from dependency_injector import containers, providers

from src.app.analysis.container import AnalysisContainer
from src.app.reports.container import ReportsContainer
from src.app.storage.container import StorageContainer
from src.app.agent.container import AgentContainer
from src.app.users.container import UserContainer
from src.app.farm_management.container import FarmManagementContainer
from src.app.auth.container import AuthContainer
from src.app.database import get_session_factory
from src.app.weather_zones.container import WeatherZonesContainer
from src.app.weather_data.container import WeatherDataContainer

class Container(containers.DeclarativeContainer):
    """Root container for the application.
    Configuration is loaded and applied in src/__init__.py
    """
    
    config = providers.Configuration(
        # This will be populated by from_dict() in src/__init__.py
        # with the fully resolved configuration (defaults, yaml, env vars).
    )
    
    # Database session factory (shared between containers)
    db_session_factory = providers.Singleton(
        lambda: get_session_factory()
    )
    
    # Analysis container: receives the 'analysis_services' section of the main config.
    analysis = providers.Container(
        AnalysisContainer,
        config=config.analysis_services # Pass the specific config section
    ) 

    # Reports container (assuming it doesn't need direct config from the root or has its own simple config)
    reports = providers.Container(
        ReportsContainer,
        app_config=config
    )

    # Storage container: receives the 'storage' section of the main config.
    storage = providers.Container(
        StorageContainer,
        config=config.storage # Pass the specific config section
    )

    # Agent container: receives the main app_config (as it expects 'agent_llm' sub-key)
    # and the reports_service from the ReportsContainer.
    agent = providers.Container(
        AgentContainer,
        app_config=config,
        reports_service=reports.reports_service
    ) 

    # Farm Management container (New)
    farm_management = providers.Container(
        FarmManagementContainer,
        config=config.farm_management, # Use provider, not dict
        db_session_factory=db_session_factory # Use the shared session factory
    ) 

    # Users container
    users = providers.Container(
        UserContainer,
        config=config, # Assuming it might need root config or will have its own
        db_session_factory=db_session_factory # Use the shared session factory
    ) 

    # Auth container
    auth = providers.Container(
        AuthContainer,
        config=config.auth,
        user_service=users.user_service
    )

    # Weather Zones
    weather_zones = providers.Container(
        WeatherZonesContainer,
        session_factory=db_session_factory,
        field_service=farm_management.field_service
    )

    # Weather Data container
    weather_data = providers.Container(
        WeatherDataContainer,
        config=config.weather_data,
        db_session_factory=db_session_factory
    )