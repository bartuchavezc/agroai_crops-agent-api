from dependency_injector import containers, providers

from .search.tavily import TavilyAdapter
from .weather.openweather import OpenWeatherAdapter
from .weather.service import WeatherService
from .weather.smn import SMNForecastETL


class ProvidersContainer(containers.DeclarativeContainer):
    """External data providers (weather today; sensors / IoT later)."""

    config = providers.Configuration()
    db_session_factory = providers.Dependency()

    search = providers.Singleton(TavilyAdapter, api_key=config.search.tavily_api_key)

    openweather = providers.Singleton(
        OpenWeatherAdapter, api_key=config.weather.openweather_api_key, timeout=10
    )
    weather_service = providers.Singleton(
        WeatherService,
        session_factory=db_session_factory,
        openweather=openweather,
        current_cache_ttl=config.weather.current_cache_ttl,
        timezone_name=config.app.timezone,
        smn_hourly_step=config.weather.smn.hourly_step,
    )
    smn_etl = providers.Singleton(
        SMNForecastETL,
        session_factory=db_session_factory,
        cache_dir=config.weather.smn.grid_cache_dir,
        horizon_hours=config.weather.smn.horizon_hours,
        hourly_step=config.weather.smn.hourly_step,
    )
