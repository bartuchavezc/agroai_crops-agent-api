from redis.asyncio import Redis
from typing import Optional, List
from datetime import datetime
from ..domain.entities import WeatherData
from ..domain.repositories import CacheWeatherRepository
from .entities.redis_weather_cache import (
    RedisWeatherCache, 
    RedisForecastCache,
    weather_data_to_redis_cache,
    redis_cache_to_weather_data
)
import logging

logger = logging.getLogger(__name__)

class RedisRepository(CacheWeatherRepository):
    """Redis repository for weather data caching with optimized storage."""
    
    def __init__(self, redis_client: Redis, ttl: int = 3600):
        self.redis = redis_client
        self.default_ttl = ttl
    
    async def add(self, weather_data: WeatherData) -> WeatherData:
        """Add (cache) weather data to Redis."""
        await self.set_latest(weather_data, self.default_ttl)
        return weather_data
    
    async def get(self, id: int) -> Optional[WeatherData]:
        """Get weather data by ID (Redis doesn't support by ID, returns None)."""
        # Redis cache doesn't support getting by ID
        return None
    
    async def list(self) -> List[WeatherData]:
        """List all cached weather data."""
        try:
            # Get all latest weather data keys
            keys = await self.redis.keys("weather:latest:*")
            weather_list = []
            
            for key in keys:
                data = await self.redis.get(key)
                if data:
                    redis_cache = RedisWeatherCache.from_json(data)
                    weather_data = redis_cache_to_weather_data(redis_cache)
                    weather_list.append(weather_data)
            
            return weather_list
        except Exception as e:
            logger.error(f"Error listing weather data from Redis: {e}")
            return []
    
    async def get_latest(self, latitude: float, longitude: float) -> Optional[WeatherData]:
        """Get latest cached weather data for location."""
        key = f"weather:latest:{latitude}:{longitude}"
        try:
            data = await self.redis.get(key)
            if data:
                redis_cache = RedisWeatherCache.from_json(data)
                return redis_cache_to_weather_data(redis_cache)
            return None
        except Exception as e:
            logger.error(f"Error getting latest weather from Redis: {e}")
            return None
    
    async def set_latest(self, weather_data: WeatherData, ttl_seconds: int = 3600) -> None:
        """Cache latest weather data for location."""
        try:
            redis_cache = weather_data_to_redis_cache(
                weather_data, 
                cache_type="latest", 
                ttl_seconds=ttl_seconds
            )
            
            await self.redis.set(
                redis_cache.cache_key,
                redis_cache.to_json(),
                ex=ttl_seconds
            )
            logger.debug(f"Cached latest weather data for {weather_data.latitude}, {weather_data.longitude}")
        except Exception as e:
            logger.error(f"Error caching latest weather to Redis: {e}")
    
    async def get_forecast(self, latitude: float, longitude: float) -> Optional[List[WeatherData]]:
        """Get cached forecast data for location."""
        # Look for today's forecast
        today = datetime.now().date()
        key = f"weather:forecast:{latitude}:{longitude}:{today}"
        
        try:
            data = await self.redis.get(key)
            if data:
                forecast_cache = RedisForecastCache.from_json(data)
                # Convert forecast_data list back to WeatherData objects
                weather_list = []
                for item in forecast_cache.forecast_data:
                    if isinstance(item, dict):
                        # Convert dict back to WeatherData
                        item['timestamp'] = datetime.fromisoformat(item['timestamp'])
                        weather_list.append(WeatherData(**item))
                return weather_list
            return None
        except Exception as e:
            logger.error(f"Error getting forecast from Redis: {e}")
            return None
    
    async def set_forecast(
        self, 
        latitude: float, 
        longitude: float, 
        forecast_data: List[WeatherData], 
        ttl_seconds: int = 86400
    ) -> None:
        """Cache forecast data for location."""
        try:
            # Convert WeatherData list to serializable format
            forecast_list = []
            for weather in forecast_data:
                forecast_list.append(weather.to_dict())
            
            forecast_cache = RedisForecastCache(
                latitude=latitude,
                longitude=longitude,
                forecast_date=datetime.now(),
                forecast_data=forecast_list,
                ttl_seconds=ttl_seconds
            )
            
            await self.redis.set(
                forecast_cache.cache_key,
                forecast_cache.to_json(),
                ex=ttl_seconds
            )
            logger.debug(f"Cached forecast data for {latitude}, {longitude} with {len(forecast_data)} items")
        except Exception as e:
            logger.error(f"Error caching forecast to Redis: {e}")
    
    async def clear_location_cache(self, latitude: float, longitude: float) -> None:
        """Clear all cached data for a specific location."""
        try:
            # Clear latest data
            latest_key = f"weather:latest:{latitude}:{longitude}"
            await self.redis.delete(latest_key)
            
            # Clear forecast data (search by pattern)
            forecast_pattern = f"weather:forecast:{latitude}:{longitude}:*"
            forecast_keys = await self.redis.keys(forecast_pattern)
            if forecast_keys:
                await self.redis.delete(*forecast_keys)
            
            logger.debug(f"Cleared cache for location {latitude}, {longitude}")
        except Exception as e:
            logger.error(f"Error clearing location cache: {e}")
    
    # Additional helper methods for debugging and monitoring
    async def get_cache_stats(self) -> dict:
        """Get cache statistics for monitoring."""
        try:
            total_keys = len(await self.redis.keys("weather:*"))
            latest_keys = len(await self.redis.keys("weather:latest:*"))
            forecast_keys = len(await self.redis.keys("weather:forecast:*"))
            
            return {
                "total_weather_keys": total_keys,
                "latest_data_keys": latest_keys,
                "forecast_keys": forecast_keys
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}
    
    async def clear_expired_cache(self) -> int:
        """Manually clear expired cache entries (for cleanup)."""
        try:
            # Redis handles TTL automatically, but this can be used for manual cleanup
            all_keys = await self.redis.keys("weather:*")
            expired_count = 0
            
            for key in all_keys:
                ttl = await self.redis.ttl(key)
                if ttl == -2:  # Key doesn't exist (expired)
                    expired_count += 1
            
            return expired_count
        except Exception as e:
            logger.error(f"Error checking expired cache: {e}")
            return 0 