from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
from datetime import datetime
import json

@dataclass
class RedisWeatherCache:
    """Redis-specific entity for weather data caching."""
    
    # Weather data
    latitude: float
    longitude: float
    timestamp: datetime
    temperature: float
    humidity: float
    precipitation: float
    wind_speed: float
    wind_direction: float
    pressure: float
    soil_moisture: Optional[float] = None
    
    # Cache metadata
    cache_type: str = "latest"  # latest, forecast, historical
    ttl_seconds: int = 3600
    data_source: str = "smn"
    
    @property
    def cache_key(self) -> str:
        """Generate Redis key for this weather data."""
        if self.cache_type == "latest":
            return f"weather:latest:{self.latitude}:{self.longitude}"
        elif self.cache_type == "forecast":
            return f"weather:forecast:{self.latitude}:{self.longitude}:{self.timestamp.date()}"
        else:
            return f"weather:{self.cache_type}:{self.latitude}:{self.longitude}:{self.timestamp.isoformat()}"
    
    def to_redis_dict(self) -> Dict[str, Any]:
        """Convert to Redis-serializable dictionary."""
        data = asdict(self)
        # Convert datetime to ISO string for JSON serialization
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    def to_json(self) -> str:
        """Convert to JSON string for Redis storage."""
        return json.dumps(self.to_redis_dict())
    
    @classmethod
    def from_redis_dict(cls, data: Dict[str, Any]) -> "RedisWeatherCache":
        """Create instance from Redis dictionary."""
        # Convert timestamp string back to datetime
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> "RedisWeatherCache":
        """Create instance from JSON string."""
        data = json.loads(json_str)
        return cls.from_redis_dict(data)

@dataclass
class RedisForecastCache:
    """Redis entity for forecast data caching."""
    
    latitude: float
    longitude: float
    forecast_date: datetime
    forecast_data: list  # List of weather forecasts for the day
    ttl_seconds: int = 86400  # 24 hours for forecasts
    data_source: str = "smn"
    
    @property
    def cache_key(self) -> str:
        """Generate Redis key for forecast data."""
        return f"weather:forecast:{self.latitude}:{self.longitude}:{self.forecast_date.date()}"
    
    def to_json(self) -> str:
        """Convert to JSON string for Redis storage."""
        data = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'forecast_date': self.forecast_date.isoformat(),
            'forecast_data': self.forecast_data,
            'ttl_seconds': self.ttl_seconds,
            'data_source': self.data_source
        }
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, json_str: str) -> "RedisForecastCache":
        """Create instance from JSON string."""
        data = json.loads(json_str)
        data['forecast_date'] = datetime.fromisoformat(data['forecast_date'])
        return cls(**data)

# Helper functions for converting between domain and cache entities
def weather_data_to_redis_cache(
    weather_data, 
    cache_type: str = "latest", 
    ttl_seconds: int = 3600
) -> RedisWeatherCache:
    """Convert domain WeatherData to Redis cache entity."""
    return RedisWeatherCache(
        latitude=weather_data.latitude,
        longitude=weather_data.longitude,
        timestamp=weather_data.timestamp,
        temperature=weather_data.temperature,
        humidity=weather_data.humidity,
        precipitation=weather_data.precipitation,
        wind_speed=weather_data.wind_speed,
        wind_direction=weather_data.wind_direction,
        pressure=weather_data.pressure,
        soil_moisture=weather_data.soil_moisture,
        cache_type=cache_type,
        ttl_seconds=ttl_seconds
    )

def redis_cache_to_weather_data(redis_cache: RedisWeatherCache):
    """Convert Redis cache entity to domain WeatherData."""
    from ...domain.entities import WeatherData
    return WeatherData(
        latitude=redis_cache.latitude,
        longitude=redis_cache.longitude,
        timestamp=redis_cache.timestamp,
        temperature=redis_cache.temperature,
        humidity=redis_cache.humidity,
        precipitation=redis_cache.precipitation,
        wind_speed=redis_cache.wind_speed,
        wind_direction=redis_cache.wind_direction,
        pressure=redis_cache.pressure,
        soil_moisture=redis_cache.soil_moisture
    ) 