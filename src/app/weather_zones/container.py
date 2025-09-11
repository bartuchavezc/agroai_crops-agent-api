from dependency_injector import containers, providers
from src.app.weather_zones.infrastructure.weather_zone_repository_impl import SQLAlchemyWeatherZoneRepository

from .domain.repositories.weather_zone_repository import WeatherZoneRepository
from .service.zone_management import ZoneManagementService

class WeatherZonesContainer(containers.DeclarativeContainer):
    # Dependencies
    session_factory = providers.Dependency()
    field_service = providers.Dependency()

    # Repositories
    weather_zone_repository = providers.Factory(
        SQLAlchemyWeatherZoneRepository,
        session_factory=session_factory
    )

    # Services
    zone_management_service = providers.Singleton(
        ZoneManagementService,
        zone_repository=weather_zone_repository,
        field_service=field_service
    ) 