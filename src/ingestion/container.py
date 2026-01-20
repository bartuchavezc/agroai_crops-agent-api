# src/ingestion/container.py
"""
Dependency injection container for the Ingestion layer.
"""
from dependency_injector import containers, providers

from .reception.adapters.smn_adapter import SMNAdapter
from .reception.adapters.openweather_adapter import OpenWeatherAdapter
from .queues.redis_queue import RedisQueue
from .queues.memory_queue import MemoryQueue
from .managers.weather_manager import WeatherManager, CurrentWeatherService
from .managers.image_manager import ImageManager
from .managers.event_router import EventRouter


class IngestionContainer(containers.DeclarativeContainer):
    """Container for ingestion-related services."""
    
    # Configuration (will be provided by parent container)
    config = providers.Configuration()
    
    # Database session factory (will be provided by parent container)
    db_session_factory = providers.Dependency()
    
    # ============================================
    # ADAPTERS
    # ============================================
    
    smn_adapter = providers.Singleton(SMNAdapter)
    
    openweather_adapter = providers.Singleton(
        OpenWeatherAdapter,
        api_key=config.weather_data.current_weather.openweather_api_key,
        timeout=10,
    )
    
    # ============================================
    # QUEUES
    # ============================================
    
    # Queue factory - returns appropriate implementation based on config
    message_queue = providers.Selector(
        config.queues.backend,
        redis=providers.Singleton(
            RedisQueue,
            host=config.queues.redis.host,
            port=config.queues.redis.port,
            db=config.queues.redis.db,
        ),
        memory=providers.Singleton(MemoryQueue),
    )
    
    # ============================================
    # MANAGERS
    # ============================================
    
    weather_manager = providers.Factory(
        WeatherManager,
        smn_adapter=smn_adapter,
        openweather_adapter=openweather_adapter,
        # Repositories will be wired from shared container
        weather_repository=None,
        cache_repository=None,
        timeseries_repository=None,
        zone_service=None,
    )
    
    current_weather_service = providers.Factory(
        CurrentWeatherService,
        openweather_adapter=openweather_adapter,
        cache_repository=None,
        cache_ttl=config.weather_data.current_weather.cache_ttl,
    )
    
    image_manager = providers.Factory(
        ImageManager,
        queue=message_queue,
        storage_service=None,  # Will be wired from action container
        reports_service=None,  # Will be wired from action container
    )
    
    event_router = providers.Factory(
        EventRouter,
        queue=message_queue,
        max_concurrent=10,
    )
    
    # ============================================
    # SERVICE ALIASES (for backward compatibility)
    # ============================================
    
    weather_service = providers.Factory(
        WeatherManager,
        smn_adapter=smn_adapter,
        openweather_adapter=openweather_adapter,
    )
    
    weather_batch_service = weather_manager
