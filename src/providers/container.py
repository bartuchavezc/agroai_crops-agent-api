from dependency_injector import containers, providers

from .satellite.copernicus import CopernicusAdapter
from .search.tavily import TavilyAdapter
from .weather.nasa_power import NasaPowerAdapter
from .weather.open_meteo import OpenMeteoAdapter
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
    open_meteo = providers.Singleton(OpenMeteoAdapter, timeout=15)
    nasa_power = providers.Singleton(NasaPowerAdapter, timeout=15)
    copernicus = providers.Singleton(
        CopernicusAdapter,
        client_id=config.satellite.copernicus_client_id,
        client_secret=config.satellite.copernicus_client_secret,
        timeout=30,
    )
    weather_service = providers.Singleton(
        WeatherService,
        session_factory=db_session_factory,
        openweather=openweather,
        open_meteo=open_meteo,
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
