# src/ingestion/reception/adapters/openweather_adapter.py
"""
OpenWeatherMap API adapter for current weather data.
"""
import aiohttp
import logging
from typing import Optional, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CurrentWeatherData:
    """Data class for current weather data."""
    temperature: float
    feels_like: float
    humidity: float
    pressure: float
    wind_speed: float
    wind_direction: float
    description: str
    icon: str
    visibility: Optional[float] = None
    clouds: Optional[float] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "temperature": self.temperature,
            "feels_like": self.feels_like,
            "humidity": self.humidity,
            "pressure": self.pressure,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "description": self.description,
            "icon": self.icon,
            "visibility": self.visibility,
            "clouds": self.clouds,
        }


class OpenWeatherAdapter:
    """
    Adapter for fetching current weather from OpenWeatherMap API.
    
    Provides real-time weather data for any location worldwide.
    Requires an API key from OpenWeatherMap.
    """
    
    BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
    
    def __init__(self, api_key: str, timeout: int = 10):
        """
        Initialize OpenWeather adapter.
        
        Args:
            api_key: OpenWeatherMap API key
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.timeout = timeout
    
    async def get_current_weather(
        self,
        latitude: float,
        longitude: float
    ) -> Optional[CurrentWeatherData]:
        """
        Get current weather for a location.
        
        Args:
            latitude: Location latitude
            longitude: Location longitude
            
        Returns:
            CurrentWeatherData or None if fetch fails
        """
        if not self.api_key:
            logger.warning("OpenWeatherMap API key not configured")
            return None
        
        params = {
            "lat": latitude,
            "lon": longitude,
            "appid": self.api_key,
            "units": "metric",  # Celsius, m/s
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BASE_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"OpenWeatherMap API error: {response.status} - {error_text}")
                        return None
                    
                    data = await response.json()
                    return self._parse_response(data)
                    
        except aiohttp.ClientError as e:
            logger.error(f"HTTP error fetching weather: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching weather: {e}")
            return None
    
    def _parse_response(self, data: Dict) -> CurrentWeatherData:
        """Parse OpenWeatherMap API response."""
        main = data.get("main", {})
        wind = data.get("wind", {})
        weather = data.get("weather", [{}])[0]
        
        return CurrentWeatherData(
            temperature=main.get("temp", 0),
            feels_like=main.get("feels_like", 0),
            humidity=main.get("humidity", 0),
            pressure=main.get("pressure", 0),
            wind_speed=wind.get("speed", 0),
            wind_direction=wind.get("deg", 0),
            description=weather.get("description", ""),
            icon=weather.get("icon", ""),
            visibility=data.get("visibility"),
            clouds=data.get("clouds", {}).get("all"),
        )
    
    async def health_check(self) -> Dict:
        """
        Check if the OpenWeatherMap API is accessible.
        
        Returns:
            Dictionary with health status
        """
        if not self.api_key:
            return {
                "status": "unhealthy",
                "message": "API key not configured"
            }
        
        try:
            # Test with Buenos Aires coordinates
            result = await self.get_current_weather(-34.6037, -58.3816)
            if result:
                return {
                    "status": "healthy",
                    "message": "OpenWeatherMap API is accessible"
                }
            else:
                return {
                    "status": "degraded",
                    "message": "API accessible but returned no data"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "message": str(e)
            }
