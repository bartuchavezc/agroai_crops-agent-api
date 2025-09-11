from datetime import datetime
from typing import List, Dict, Tuple, Optional
from uuid import UUID
import logging
import asyncio

from ..domain.entities import WeatherData
from ..infrastructure.smn_client import SMNClient
from ..domain.repositories import TimeseriesWeatherRepository, WeatherRepository, CacheWeatherRepository
from ...weather_zones.domain.weather_zone_repository import WeatherZoneRepository

logger = logging.getLogger(__name__)

class WeatherBatchService:
    """Servicio optimizado para procesamiento masivo de datos meteorológicos por zonas activas."""
    
    def __init__(self,
                 zone_repository: WeatherZoneRepository,
                 smn_client: SMNClient,
                 weather_repository: WeatherRepository,
                 cache_repository: CacheWeatherRepository,
                 timeseries_repository: TimeseriesWeatherRepository):
        self.zone_repository = zone_repository
        self.smn_client = smn_client
        self.weather_repository = weather_repository
        self.cache_repository = cache_repository
        self.timeseries_repository: TimeseriesWeatherRepository = timeseries_repository
    
    async def get_active_zone_coordinates(self) -> List[Tuple[float, float, UUID, str]]:
        """
        Obtiene las coordenadas de todas las zonas activas.
        Returns: Lista de tuplas (latitude, longitude, zone_id, zone_name)
        """
        try:
            zones = await self.zone_repository.get_all_active()
            coordinates = [
                (zone.center_latitude, zone.center_longitude, zone.id, zone.name)
                for zone in zones
            ]
            logger.info(f"Obtenidas {len(coordinates)} zonas activas para procesamiento")
            return coordinates
        except Exception as e:
            logger.error(f"Error obteniendo coordenadas de zonas activas: {e}")
            return []
    
    async def fetch_zone_weather_data(self, 
                                    latitude: float, 
                                    longitude: float, 
                                    zone_id: UUID,
                                    zone_name: str,
                                    target_date: Optional[datetime] = None) -> Optional[WeatherData]:
        """
        Obtiene datos meteorológicos para una zona específica.
        """
        try:
            date_to_fetch = target_date if target_date is not None else datetime.now()
            
            # Obtener datos del SMN
            smn_data = await self.smn_client.get_forecast(date_to_fetch, latitude, longitude)
            if not smn_data:
                logger.warning(f"No se pudieron obtener datos SMN para zona {zone_name} ({latitude}, {longitude})")
                return None
            
            # Crear entidad WeatherData
            weather_data = WeatherData(
                id=None,
                timestamp=date_to_fetch,
                latitude=latitude,
                longitude=longitude,
                **smn_data
            )
            
            logger.debug(f"✅ Datos obtenidos para zona {zone_name}: T={smn_data.get('temperature', 'N/A')}°C")
            return weather_data
            
        except Exception as e:
            logger.error(f"Error obteniendo datos para zona {zone_name}: {e}")
            return None
    
    async def fetch_all_zones_weather(self, target_date: Optional[datetime] = None) -> List[WeatherData]:
        """
        Obtiene datos meteorológicos para todas las zonas activas usando batch optimizado.
        """
        start_time = datetime.now()
        coordinates_data = await self.get_active_zone_coordinates()
        
        if not coordinates_data:
            logger.warning("No hay zonas activas para procesar")
            return []
        
        date_to_fetch = target_date if target_date is not None else datetime.now()
        
        logger.info(f"🚀 Iniciando fetch batch optimizado para {len(coordinates_data)} zonas...")
        
        # Extraer solo las coordenadas para el batch
        coordinates = [(lat, lon) for lat, lon, zone_id, zone_name in coordinates_data]
        
        # Usar método batch optimizado del SMNClient
        smn_results = await self.smn_client.get_forecast_batch(coordinates, date_to_fetch)
        
        # Combinar resultados con metadata de zonas
        weather_data_list = []
        successful = 0
        
        for i, (lat, lon, zone_id, zone_name) in enumerate(coordinates_data):
            smn_data = smn_results[i] if i < len(smn_results) else None
            
            if smn_data:
                weather_data = WeatherData(
                    id=None,
                    timestamp=date_to_fetch,
                    latitude=lat,
                    longitude=lon,
                    **smn_data
                )
                weather_data_list.append(weather_data)
                successful += 1
                logger.debug(f"✅ Zona {zone_name}: T={smn_data.get('temperature', 'N/A')}°C")
            else:
                logger.warning(f"❌ Sin datos para zona {zone_name} ({lat}, {lon})")
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"✅ Fetch batch completado: {successful}/{len(coordinates_data)} zonas en {duration:.2f}s")
        
        return weather_data_list
    
    async def store_weather_data_batch(self, weather_data_list: List[WeatherData]) -> Dict[str, int]:
        """
        Almacena datos meteorológicos en lote en todos los repositorios.
        """
        if not weather_data_list:
            return {"stored": 0, "cached": 0, "timeseries": 0}
        
        logger.info(f"📦 Almacenando {len(weather_data_list)} registros en lote...")
        
        try:
            # Almacenar en PostgreSQL (principal)
            stored_data = []
            for weather_data in weather_data_list:
                stored = await self.weather_repository.add(weather_data)
                if stored:
                    stored_data.append(stored)
            
            # Almacenar en Cache (Redis) - solo los más recientes
            cache_count = 0
            for weather_data in stored_data:
                try:
                    await self.cache_repository.add(weather_data)
                    cache_count += 1
                except Exception as e:
                    logger.warning(f"Error en cache para {weather_data.latitude}, {weather_data.longitude}: {e}")
            
            # Almacenar en TimescaleDB (series de tiempo)
            timeseries_stored = await self.timeseries_repository.save_batch(stored_data)
            
            result = {
                "stored": len(stored_data),
                "cached": cache_count,
                "timeseries": len(timeseries_stored) if timeseries_stored else 0
            }
            
            logger.info(f"✅ Almacenamiento completado: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error en almacenamiento en lote: {e}")
            return {"stored": 0, "cached": 0, "timeseries": 0}
    
    async def populate_all_zones_weather(self, target_date: Optional[datetime] = None) -> Dict[str, int]:
        """
        Proceso completo: obtiene y almacena datos meteorológicos para todas las zonas activas.
        """
        logger.info("🌦️  Iniciando populado masivo de datos meteorológicos...")
        
        # 1. Fetch masivo de datos
        weather_data_list = await self.fetch_all_zones_weather(target_date)
        
        if not weather_data_list:
            logger.warning("No se obtuvieron datos meteorológicos")
            return {"zones_processed": 0, "stored": 0, "cached": 0, "timeseries": 0}
        
        # 2. Almacenamiento en lote
        storage_result = await self.store_weather_data_batch(weather_data_list)
        
        # 3. Resultado final
        final_result = {
            "zones_processed": len(weather_data_list),
            **storage_result
        }
        
        logger.info(f"🎯 Populado completado: {final_result}")
        return final_result 