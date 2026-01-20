# src/ingestion/managers/weather_manager.py
"""
Weather data manager - processes weather data events.

Handles:
- Weather data fetching from external sources
- Data normalization and storage
- Batch processing for multiple zones
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from ..queues.interfaces import Message

logger = logging.getLogger(__name__)


@dataclass
class WeatherData:
    """Normalized weather data entity."""
    id: Optional[int]
    timestamp: datetime
    latitude: float
    longitude: float
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    pressure: Optional[float] = None
    soil_moisture: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "temperature": self.temperature,
            "humidity": self.humidity,
            "precipitation": self.precipitation,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "pressure": self.pressure,
            "soil_moisture": self.soil_moisture,
        }


class WeatherManager:
    """
    Manager for weather data processing.
    
    Handles message processing from the queue and coordinates
    with adapters, repositories, and cache.
    """
    
    def __init__(
        self,
        smn_adapter,
        openweather_adapter,
        weather_repository=None,
        cache_repository=None,
        timeseries_repository=None,
        zone_service=None,
    ):
        """
        Initialize weather manager.
        
        Args:
            smn_adapter: SMN data adapter
            openweather_adapter: OpenWeatherMap adapter
            weather_repository: Main weather data repository
            cache_repository: Cache repository (Redis)
            timeseries_repository: TimescaleDB repository
            zone_service: Weather zone service for batch operations
        """
        self.smn_adapter = smn_adapter
        self.openweather_adapter = openweather_adapter
        self.weather_repository = weather_repository
        self.cache_repository = cache_repository
        self.timeseries_repository = timeseries_repository
        self.zone_service = zone_service
    
    async def handle_message(self, message: Message) -> Any:
        """
        Handle incoming weather message.
        
        Args:
            message: Message to process
            
        Returns:
            Processing result
        """
        payload = message.payload
        
        if message.type == "weather.fetch":
            return await self.fetch_weather_data(
                latitude=payload.get("latitude"),
                longitude=payload.get("longitude"),
                target_date=payload.get("target_date"),
            )
        elif message.type == "weather.batch_fetch":
            return await self.populate_all_zones_weather(
                target_date=payload.get("target_date"),
            )
        else:
            logger.warning(f"Unknown weather message type: {message.type}")
            return None
    
    async def fetch_weather_data(
        self,
        latitude: float,
        longitude: float,
        target_date: Optional[datetime] = None,
    ) -> Optional[WeatherData]:
        """
        Fetch and store weather data for a location.
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            target_date: Target date (defaults to now)
            
        Returns:
            WeatherData entity if successful
        """
        try:
            date_to_fetch = target_date or datetime.now()
            
            # Get data from SMN
            smn_data = await self.smn_adapter.get_forecast(
                date_to_fetch, latitude, longitude
            )
            
            if not smn_data:
                logger.warning(f"No SMN data for {date_to_fetch} at ({latitude}, {longitude})")
                return None
            
            # Create entity
            weather_data = WeatherData(
                id=None,
                timestamp=date_to_fetch,
                latitude=latitude,
                longitude=longitude,
                **smn_data
            )
            
            # Store in various repositories
            if self.cache_repository:
                await self.cache_repository.add(weather_data)
            
            if self.timeseries_repository:
                await self.timeseries_repository.store_time_series(weather_data)
            
            if self.weather_repository:
                return await self.weather_repository.add(weather_data)
            
            return weather_data
            
        except Exception as e:
            logger.error(f"Error fetching weather data: {e}")
            return None
    
    async def get_latest_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> Optional[WeatherData]:
        """
        Get latest available weather data.
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            
        Returns:
            Latest WeatherData if available
        """
        # Try cache first
        if self.cache_repository:
            cached = await self.cache_repository.get_latest(latitude, longitude)
            if cached:
                return cached
        
        # Fall back to main repository
        if self.weather_repository:
            return await self.weather_repository.get_latest(latitude, longitude)
        
        return None
    
    async def get_weather_history(
        self,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
    ) -> List[WeatherData]:
        """
        Get historical weather data.
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            start_time: History start time
            end_time: History end time
            
        Returns:
            List of WeatherData entries
        """
        if self.timeseries_repository:
            return await self.timeseries_repository.get_time_series(
                latitude, longitude, start_time, end_time
            )
        return []
    
    async def populate_all_zones_weather(
        self,
        target_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Fetch weather data for all active zones (batch operation).
        
        Args:
            target_date: Target date (defaults to now)
            
        Returns:
            Dictionary with processing results
        """
        date_to_fetch = target_date or datetime.now()
        
        result = {
            "zones_processed": 0,
            "stored": 0,
            "cached": 0,
            "timeseries": 0,
            "errors": 0,
        }
        
        if not self.zone_service:
            logger.warning("Zone service not configured for batch operations")
            return result
        
        try:
            # Get all active zones
            zones = await self.zone_service.get_all_active_zones()
            
            if not zones:
                logger.info("No active zones found")
                return result
            
            # Build coordinates list
            coordinates = [(z.latitude, z.longitude) for z in zones]
            
            # Batch fetch from SMN
            weather_results = await self.smn_adapter.get_forecast_batch(
                coordinates, date_to_fetch
            )
            
            # Process results
            for zone, weather_data in zip(zones, weather_results):
                if weather_data is None:
                    result["errors"] += 1
                    continue
                
                entity = WeatherData(
                    id=None,
                    timestamp=date_to_fetch,
                    latitude=zone.latitude,
                    longitude=zone.longitude,
                    **weather_data
                )
                
                try:
                    if self.cache_repository:
                        await self.cache_repository.add(entity)
                        result["cached"] += 1
                    
                    if self.timeseries_repository:
                        await self.timeseries_repository.store_time_series(entity)
                        result["timeseries"] += 1
                    
                    if self.weather_repository:
                        await self.weather_repository.add(entity)
                        result["stored"] += 1
                    
                    result["zones_processed"] += 1
                    
                except Exception as e:
                    logger.error(f"Error storing weather for zone {zone.id}: {e}")
                    result["errors"] += 1
            
            logger.info(f"Batch weather fetch completed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error in batch weather fetch: {e}")
            result["errors"] += 1
            return result


class CurrentWeatherService:
    """Service for real-time weather data (OpenWeatherMap)."""
    
    def __init__(self, openweather_adapter, cache_repository=None, cache_ttl: int = 900):
        """
        Initialize current weather service.
        
        Args:
            openweather_adapter: OpenWeatherMap adapter
            cache_repository: Optional cache repository
            cache_ttl: Cache TTL in seconds (default 15 minutes)
        """
        self.adapter = openweather_adapter
        self.cache = cache_repository
        self.cache_ttl = cache_ttl
    
    async def get_current_weather(self, latitude: float, longitude: float):
        """Get current weather for a location."""
        # Try cache first
        if self.cache:
            cached = await self.cache.get(f"current:{latitude}:{longitude}")
            if cached:
                return cached
        
        # Fetch from API
        data = await self.adapter.get_current_weather(latitude, longitude)
        
        # Cache result
        if data and self.cache:
            await self.cache.set(
                f"current:{latitude}:{longitude}",
                data,
                ttl=self.cache_ttl
            )
        
        return data
    
    async def health_check(self) -> Dict[str, Any]:
        """Check service health."""
        return await self.adapter.health_check()
