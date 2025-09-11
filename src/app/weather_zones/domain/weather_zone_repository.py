from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID

from src.app.weather_zones.domain.weather_zone import WeatherZone, WeatherZoneCreate, WeatherZoneUpdate


class WeatherZoneRepository(ABC):
    @abstractmethod
    async def create(self, zone: WeatherZoneCreate) -> WeatherZone:
        """Create a new weather zone"""
        pass

    @abstractmethod
    async def get(self, zone_id: UUID) -> Optional[WeatherZone]:
        """Get a weather zone by ID"""
        pass

    @abstractmethod
    async def get_all(self) -> List[WeatherZone]:
        """Get all weather zones"""
        pass

    @abstractmethod
    async def get_all_active(self) -> List[WeatherZone]:
        """Get all active weather zones"""
        pass

    @abstractmethod
    async def update(
        self,
        zone_id: UUID,
        zone: WeatherZoneUpdate
    ) -> Optional[WeatherZone]:
        """Update a weather zone"""
        pass

    @abstractmethod
    async def delete(self, zone_id: UUID) -> bool:
        """Delete a weather zone"""
        pass

    @abstractmethod
    async def get_by_coordinates(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[WeatherZone]:
        """Get all active zones within radius_km of the given coordinates"""
        pass

    @abstractmethod
    async def find_closest_zone(
        self,
        latitude: float,
        longitude: float,
        max_distance_km: float
    ) -> Optional[WeatherZone]:
        """Find the closest active zone within max_distance_km using Haversine formula"""
        pass 