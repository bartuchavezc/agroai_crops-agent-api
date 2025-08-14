from abc import ABC, abstractmethod
from typing import Generic, TypeVar, List, Optional
from datetime import datetime
from .entities import WeatherData

T = TypeVar('T')

class BaseRepository(Generic[T], ABC):
    @abstractmethod
    async def add(self, entity: T) -> T:
        pass
    
    @abstractmethod
    async def get(self, id: int) -> Optional[T]:
        pass
    
    @abstractmethod
    async def list(self) -> List[T]:
        pass

class WeatherRepository(BaseRepository[WeatherData], ABC):
    @abstractmethod
    async def get_by_location(self, 
                            latitude: float, 
                            longitude: float,
                            start_time: datetime,
                            end_time: datetime) -> List[WeatherData]:
        pass
    
    @abstractmethod
    async def get_latest(self, 
                        latitude: float, 
                        longitude: float) -> Optional[WeatherData]:
        pass

class CacheWeatherRepository(BaseRepository[WeatherData], ABC):
    @abstractmethod
    async def get_latest(self, latitude: float, longitude: float) -> Optional[WeatherData]:
        pass

class TimeseriesWeatherRepository(ABC):
    @abstractmethod
    async def store_time_series(self, data: WeatherData):
        pass
    
    @abstractmethod
    async def get_time_series(self, latitude: float, longitude: float, start_time: datetime, end_time: datetime) -> List[WeatherData]:
        pass 