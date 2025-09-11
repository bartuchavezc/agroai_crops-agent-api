from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID
import math

from ..domain.models.weather_zone import WeatherZone, WeatherZoneCreate, WeatherZoneUpdate, FieldWeatherZone
from ..domain.repositories.weather_zone_repository import WeatherZoneRepository
from ...farm_management.service.field_service import FieldService

class ZoneManagementService:
    def __init__(
        self,
        zone_repository: WeatherZoneRepository,
        field_service: FieldService
    ):
        self.zone_repository = zone_repository
        self.field_service = field_service

    def validate_coordinates(self, latitude: float, longitude: float) -> bool:
        """
        Validate that coordinates are within valid ranges.
        Latitude: -90 to 90
        Longitude: -180 to 180
        """
        return -90 <= latitude <= 90 and -180 <= longitude <= 180

    def calculate_distance(
        self,
        lat1: float,
        lon1: float,
        lat2: float,
        lon2: float
    ) -> float:
        """
        Calculate the distance between two points using the Haversine formula.
        Returns distance in kilometers.
        """
        R = 6371  # Earth's radius in kilometers

        # Convert latitude and longitude from degrees to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        
        return R * c

    async def create_zone(self, zone_data: WeatherZoneCreate) -> WeatherZone:
        """Create a new weather zone"""
        return await self.zone_repository.create(zone_data)

    async def get_zone(self, zone_id: UUID) -> Optional[WeatherZone]:
        """Get a weather zone by ID"""
        return await self.zone_repository.get(zone_id)

    async def update_zone(
        self,
        zone_id: UUID,
        zone_data: WeatherZoneUpdate
    ) -> Optional[WeatherZone]:
        """Update a weather zone"""
        return await self.zone_repository.update(zone_id, zone_data)

    async def delete_zone(self, zone_id: UUID) -> bool:
        """Delete a weather zone"""
        return await self.zone_repository.delete(zone_id)

    async def find_zone_for_field(
        self,
        field_id: UUID,
        max_distance_km: float = 10.0
    ) -> Optional[WeatherZone]:
        """
        Find the most appropriate zone for a field.
        Returns the closest active zone within max_distance_km, or None if none found.
        """
        field = await self.field_service.get_field(field_id)
        if not field:
            return None

        # Get all active zones
        zones = await self.zone_repository.get_all_active()
        
        closest_zone = None
        min_distance = float('inf')

        for zone in zones:
            distance = self.calculate_distance(
                field.latitude,
                field.longitude,
                zone.center_latitude,
                zone.center_longitude
            )
            
            if distance <= max_distance_km and distance < min_distance:
                min_distance = distance
                closest_zone = zone

        return closest_zone

    async def optimize_zones(self) -> List[WeatherZone]:
        """
        Optimize zones by:
        1. Merging overlapping zones
        2. Recalculating centers based on field distribution
        3. Adjusting radii to minimize overlap while maintaining coverage
        """
        zones = await self.zone_repository.get_all_active()
        fields = await self.field_service.get_all_fields()

        # Group fields by their current zones
        fields_by_zone = {}
        for field in fields:
            zone = await self.find_zone_for_field(field.id)
            if zone:
                if zone.id not in fields_by_zone:
                    fields_by_zone[zone.id] = []
                fields_by_zone[zone.id].append(field)

        # Recalculate zone centers and radii
        updated_zones = []
        for zone_id, zone_fields in fields_by_zone.items():
            if not zone_fields:
                continue

            # Calculate new center as average of field positions
            avg_lat = sum(f.latitude for f in zone_fields) / len(zone_fields)
            avg_lon = sum(f.longitude for f in zone_fields) / len(zone_fields)

            # Calculate new radius to cover all fields with some margin
            max_distance = max(
                self.calculate_distance(avg_lat, avg_lon, f.latitude, f.longitude)
                for f in zone_fields
            )
            new_radius = max_distance * 1.2  # 20% margin

            # Update zone
            updated_zone = await self.zone_repository.update(
                zone_id,
                WeatherZoneUpdate(
                    center_latitude=avg_lat,
                    center_longitude=avg_lon,
                    radius_km=min(new_radius, 50.0)  # Cap at 50km
                )
            )
            if updated_zone:
                updated_zones.append(updated_zone)

        return updated_zones

    async def get_zones_with_fields(self) -> List[Tuple[WeatherZone, List[UUID]]]:
        """
        Get all zones with their associated field IDs.
        Returns a list of tuples (zone, field_ids).
        """
        zones = await self.zone_repository.get_all_active()
        result = []

        for zone in zones:
            fields = await self.field_service.get_fields_by_zone(zone.id)
            field_ids = [f.id for f in fields]
            result.append((zone, field_ids))

        return result

    async def find_or_create_zone_for_field(
        self,
        field_id: UUID,
        max_distance_km: float = 10.0
    ) -> WeatherZone:
        """
        Find the closest zone for a field or create a new one if none is found within max_distance_km.
        Returns the zone (either existing or newly created).
        """
        field = await self.field_service.get_field(field_id)
        if not field:
            raise ValueError(f"Field with id {field_id} not found")

        # Validate field coordinates
        if not self.validate_coordinates(field.latitude, field.longitude):
            raise ValueError(
                f"Invalid coordinates for field {field_id}: "
                f"latitude {field.latitude} must be between -90 and 90, "
                f"longitude {field.longitude} must be between -180 and 180"
            )

        # Find closest zone using PostgreSQL's Haversine formula
        closest_zone = await self.zone_repository.find_closest_zone(
            field.latitude,
            field.longitude,
            max_distance_km
        )

        if closest_zone:
            return closest_zone

        # No zone found within max_distance_km, create a new one
        city = getattr(field, 'city', 'Unknown')
        count = await self.zone_repository.count_zones_by_city(city)
        next_number = count + 1

        new_zone = await self.zone_repository.create(
            WeatherZoneCreate(
                name=f"Zona {city} {next_number}",
                center_latitude=field.latitude,
                center_longitude=field.longitude,
                radius_km=max_distance_km,
                is_active=True
            )
        )
        return new_zone 