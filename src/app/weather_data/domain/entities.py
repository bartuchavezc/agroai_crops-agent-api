from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any

@dataclass
class WeatherData:
    """Weather data entity for storing meteorological information."""
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    precipitation: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    pressure: Optional[float] = None
    soil_moisture: Optional[float] = None

    def to_dict(self) -> dict:
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
            "soil_moisture": self.soil_moisture
        }

@dataclass
class CurrentWeatherData:
    """Entidad para datos de clima actual (OpenWeatherMap)."""
    
    latitude: float
    longitude: float
    timestamp: datetime
    temperature: float
    humidity: int
    pressure: float
    wind_speed: float
    wind_direction: int
    visibility: float
    description: str
    precipitation: float = 0.0
    feels_like: Optional[float] = None
    source: str = "openweather"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timestamp": self.timestamp.isoformat(),
            "temperature": self.temperature,
            "humidity": self.humidity,
            "pressure": self.pressure,
            "wind_speed": self.wind_speed,
            "wind_direction": self.wind_direction,
            "visibility": self.visibility,
            "description": self.description,
            "precipitation": self.precipitation,
            "feels_like": self.feels_like,
            "source": self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CurrentWeatherData":
        """Create instance from dictionary."""
        # Convert timestamp string back to datetime if needed
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data) 