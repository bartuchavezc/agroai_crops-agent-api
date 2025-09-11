from dependency_injector import containers, providers
from redis.asyncio import Redis
from src.app.weather_zones.infrastructure.weather_zone_repository_impl import SQLAlchemyWeatherZoneRepository

from .infrastructure.sqlalchemy_repository import SQLAlchemyRepository
from .infrastructure.redis_repository import RedisRepository
from .infrastructure.timeseries_repository import TimeseriesRepository
from .infrastructure.smn_client import SMNClient
from .infrastructure.openweather_client import OpenWeatherClient
from .service.weather_service import WeatherService
from .service.weather_batch_service import WeatherBatchService
from .service.current_weather_service import CurrentWeatherService

class WeatherDataContainer(containers.DeclarativeContainer):
    """Container for weather data module dependencies."""
    
    config = providers.Configuration()
    db_session_factory = providers.Dependency()
    
    # Redis client
    redis_client = providers.Singleton(
        Redis,
        host=config.redis.host,
        port=config.redis.port,
        db=config.redis.db
    )
    
    # SMN Client
    smn_client = providers.Singleton(SMNClient)
    
    # OpenWeatherMap Client
    openweather_client = providers.Singleton(
        OpenWeatherClient,
        api_key=config.current_weather.openweather_api_key
    )
    
    # Repositories
    weather_repository = providers.Factory(
        SQLAlchemyRepository,
        session_factory=db_session_factory
    )
    
    cache_repository = providers.Factory(
        RedisRepository,
        redis_client=redis_client,
        ttl=config.cache.ttl.as_int() if config.cache.ttl.provided else 3600
    )
    
    timeseries_repository = providers.Factory(
        TimeseriesRepository
    )
    
    # Weather Zone Repository (necesario para WeatherBatchService)
    weather_zone_repository = providers.Factory(
        SQLAlchemyWeatherZoneRepository,
        session_factory=db_session_factory
    )
    
    # Weather Service
    weather_service = providers.Factory(
        WeatherService,
        repository=weather_repository,
        cache_repository=cache_repository,
        timeseries_repository=timeseries_repository,
        smn_client=smn_client
    )
    
    # Weather Batch Service
    weather_batch_service = providers.Factory(
        WeatherBatchService,
        zone_repository=weather_zone_repository,
        smn_client=smn_client,
        weather_repository=weather_repository,
        cache_repository=cache_repository,
        timeseries_repository=timeseries_repository
    )
    
    # Current Weather Service (OpenWeatherMap)
    current_weather_service = providers.Factory(
        CurrentWeatherService,
        openweather_client=openweather_client,
        redis_client=redis_client,
        cache_ttl=config.current_weather.cache_ttl.as_int() if config.current_weather.cache_ttl.provided else 900  # 15 minutos
    ) 