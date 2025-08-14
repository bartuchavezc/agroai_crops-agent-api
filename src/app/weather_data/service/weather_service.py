from datetime import datetime, timedelta
from typing import List, Optional
from ..domain.entities import WeatherData
from ..domain.repositories import WeatherRepository, CacheWeatherRepository, TimeseriesWeatherRepository
from ..infrastructure.smn_client import SMNClient
import logging

logger = logging.getLogger(__name__)

class WeatherService:
    def __init__(self, 
                 repository: WeatherRepository,
                 cache_repository: CacheWeatherRepository,
                 timeseries_repository: TimeseriesWeatherRepository,
                 smn_client: SMNClient):
        self.repository = repository
        self.cache_repository = cache_repository
        self.timeseries_repository = timeseries_repository
        self.smn_client = smn_client
    
    async def fetch_and_store_weather_data(self, 
                                         latitude: float,
                                         longitude: float,
                                         target_date: datetime = None) -> Optional[WeatherData]:
        """
        Obtiene datos del SMN y los almacena para una fecha específica o actual
        """
        try:
            # Usar fecha proporcionada o fecha actual
            date_to_fetch = target_date if target_date is not None else datetime.now()
            
            # Obtener datos del SMN usando las coordenadas específicas del usuario
            smn_data = await self.smn_client.get_forecast(date_to_fetch, latitude, longitude)
            if not smn_data:
                logger.warning(f"No se pudieron obtener datos SMN para {date_to_fetch} en ({latitude}, {longitude})")
                return None
            
            # Crear entidad WeatherData
            weather_data = WeatherData(
                id=None,
                timestamp=date_to_fetch,
                latitude=latitude,
                longitude=longitude,
                **smn_data
            )
            
            # Almacenar en cache para acceso rápido
            await self.cache_repository.add(weather_data)
            
            # Almacenar en timeseries para históricos
            await self.timeseries_repository.store_time_series(weather_data)
            
            # Almacenar en repositorio principal
            return await self.repository.add(weather_data)
            
        except Exception as e:
            logger.error(f"Error en fetch_and_store_weather_data: {e}")
            return None
    
    async def get_latest_weather(self, 
                               latitude: float,
                               longitude: float) -> Optional[WeatherData]:
        """
        Obtiene el último dato meteorológico disponible
        """
        # Intentar primero desde cache
        cached_data = await self.cache_repository.get_latest(latitude, longitude)
        if cached_data:
            return cached_data
        
        # Si no hay en cache, buscar en repositorio principal
        return await self.repository.get_latest(latitude, longitude)
    
    async def get_weather_history(self,
                                latitude: float,
                                longitude: float,
                                start_time: datetime,
                                end_time: datetime) -> List[WeatherData]:
        """
        Obtiene historial de datos meteorológicos
        """
        return await self.timeseries_repository.get_time_series(
            latitude, longitude, start_time, end_time
        ) 