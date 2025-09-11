from datetime import datetime
from typing import Optional
from redis.asyncio import Redis
import json
import logging

from ..domain.entities import CurrentWeatherData
from ..infrastructure.openweather_client import OpenWeatherClient

logger = logging.getLogger(__name__)

class CurrentWeatherService:
    """Servicio para obtener clima actual usando OpenWeatherMap con cache Redis."""
    
    def __init__(self, openweather_client: OpenWeatherClient, redis_client: Redis, cache_ttl: int = 900):
        self.openweather_client = openweather_client
        self.redis = redis_client
        self.cache_ttl = cache_ttl  # 15 minutos por defecto
    
    def _get_cache_key(self, latitude: float, longitude: float) -> str:
        """Genera la key de Redis para clima actual."""
        return f"weather:current:{latitude}:{longitude}"
    
    async def get_current_weather(self, latitude: float, longitude: float) -> Optional[CurrentWeatherData]:
        """
        Obtiene el clima actual para coordenadas específicas.
        
        Flujo:
        1. Buscar en cache Redis
        2. Si no existe o expiró, consultar OpenWeatherMap
        3. Guardar en cache y retornar
        
        Args:
            latitude: Latitud de la ubicación
            longitude: Longitud de la ubicación
            
        Returns:
            CurrentWeatherData o None si hay error
        """
        cache_key = self._get_cache_key(latitude, longitude)
        
        try:
            # 1. Intentar obtener desde cache
            cached_data = await self._get_from_cache(cache_key)
            if cached_data:
                logger.debug(f"📋 Clima actual desde cache para ({latitude:.4f}, {longitude:.4f})")
                return cached_data
            
            # 2. Cache miss - consultar OpenWeatherMap
            logger.debug(f"🌐 Cache miss - consultando OpenWeatherMap para ({latitude:.4f}, {longitude:.4f})")
            weather_data = await self.openweather_client.get_current_weather(latitude, longitude)
            
            if not weather_data:
                logger.warning(f"No se pudo obtener clima actual para ({latitude:.4f}, {longitude:.4f})")
                return None
            
            # 3. Crear entidad y guardar en cache
            current_weather = CurrentWeatherData(
                latitude=latitude,
                longitude=longitude,
                timestamp=weather_data.get("timestamp", datetime.now()),
                temperature=weather_data.get("temperature", 0.0),
                humidity=weather_data.get("humidity", 0),
                pressure=weather_data.get("pressure", 0.0),
                wind_speed=weather_data.get("wind_speed", 0.0),
                wind_direction=weather_data.get("wind_direction", 0),
                visibility=weather_data.get("visibility", 0.0),
                description=weather_data.get("description", ""),
                precipitation=weather_data.get("precipitation", 0.0),
                feels_like=weather_data.get("feels_like"),
                source="openweather"
            )
            
            # 4. Guardar en cache
            await self._save_to_cache(cache_key, current_weather)
            
            logger.info(f"✅ Clima actual obtenido: {current_weather.temperature}°C, {current_weather.description}")
            return current_weather
            
        except Exception as e:
            logger.error(f"Error obteniendo clima actual para ({latitude:.4f}, {longitude:.4f}): {e}")
            return None
    
    async def _get_from_cache(self, cache_key: str) -> Optional[CurrentWeatherData]:
        """Obtiene datos del clima desde Redis cache."""
        try:
            cached_json = await self.redis.get(cache_key)
            if cached_json:
                data = json.loads(cached_json)
                return CurrentWeatherData.from_dict(data)
            return None
        except Exception as e:
            logger.warning(f"Error leyendo cache {cache_key}: {e}")
            return None
    
    async def _save_to_cache(self, cache_key: str, weather_data: CurrentWeatherData) -> None:
        """Guarda datos del clima en Redis cache."""
        try:
            weather_json = json.dumps(weather_data.to_dict())
            await self.redis.set(cache_key, weather_json, ex=self.cache_ttl)
            logger.debug(f"💾 Clima guardado en cache por {self.cache_ttl}s: {cache_key}")
        except Exception as e:
            logger.warning(f"Error guardando en cache {cache_key}: {e}")
    
    async def clear_cache(self, latitude: float, longitude: float) -> bool:
        """Limpia el cache para una ubicación específica."""
        try:
            cache_key = self._get_cache_key(latitude, longitude)
            result = await self.redis.delete(cache_key)
            logger.info(f"🗑️ Cache limpiado para ({latitude:.4f}, {longitude:.4f})")
            return result > 0
        except Exception as e:
            logger.error(f"Error limpiando cache: {e}")
            return False
    
    async def get_cache_stats(self) -> dict:
        """Obtiene estadísticas del cache de clima actual."""
        try:
            current_keys = await self.redis.keys("weather:current:*")
            return {
                "current_weather_keys": len(current_keys),
                "cache_ttl_seconds": self.cache_ttl
            }
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de cache: {e}")
            return {}
    
    async def health_check(self) -> dict:
        """Verifica el estado del servicio de clima actual."""
        try:
            # Verificar OpenWeatherMap API
            api_healthy = await self.openweather_client.health_check()
            
            # Verificar Redis
            redis_healthy = await self.redis.ping()
            
            # Estadísticas de cache
            cache_stats = await self.get_cache_stats()
            
            return {
                "service": "current_weather",
                "openweather_api": "healthy" if api_healthy else "unhealthy",
                "redis_cache": "healthy" if redis_healthy else "unhealthy",
                "cache_ttl_minutes": self.cache_ttl // 60,
                **cache_stats
            }
        except Exception as e:
            logger.error(f"Error en health check: {e}")
            return {
                "service": "current_weather",
                "status": "error",
                "error": str(e)
            } 