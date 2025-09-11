from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.app.weather_zones.domain.weather_zone import WeatherZone, WeatherZoneCreate, WeatherZoneUpdate
from src.app.weather_zones.domain.weather_zone_repository import WeatherZoneRepository
from src.app.weather_zones.infrastructure.models.weather_zone import WeatherZone as WeatherZoneModel


class SQLAlchemyWeatherZoneRepository(WeatherZoneRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def _get_session(self) -> AsyncSession:
        return self.session_factory()

    async def create(self, zone_data: WeatherZoneCreate) -> WeatherZone:
        async with await self._get_session() as session:
            db_zone = WeatherZoneModel(
                name=zone_data.name,
                center_latitude=zone_data.center_latitude,
                center_longitude=zone_data.center_longitude,
                radius_km=zone_data.radius_km,
                is_active=zone_data.is_active,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            session.add(db_zone)
            await session.commit()
            await session.refresh(db_zone)
            return WeatherZone.model_validate(db_zone)

    async def get(self, zone_id: UUID) -> Optional[WeatherZone]:
        async with await self._get_session() as session:
            result = await session.execute(
                select(WeatherZoneModel).where(WeatherZoneModel.id == zone_id)
            )
            db_zone = result.scalar_one_or_none()
            return WeatherZone.model_validate(db_zone) if db_zone else None

    async def get_all(self) -> List[WeatherZone]:
        async with await self._get_session() as session:
            result = await session.execute(select(WeatherZoneModel))
            db_zones = result.scalars().all()
            return [WeatherZone.model_validate(zone) for zone in db_zones]

    async def get_all_active(self) -> List[WeatherZone]:
        async with await self._get_session() as session:
            result = await session.execute(
                select(WeatherZoneModel).where(WeatherZoneModel.is_active == True)
            )
            db_zones = result.scalars().all()
            return [WeatherZone.model_validate(zone) for zone in db_zones]

    async def update(
        self,
        zone_id: UUID,
        zone_data: WeatherZoneUpdate
    ) -> Optional[WeatherZone]:
        async with await self._get_session() as session:
            result = await session.execute(
                select(WeatherZoneModel).where(WeatherZoneModel.id == zone_id)
            )
            db_zone = result.scalar_one_or_none()
            if not db_zone:
                return None

            update_data = zone_data.model_dump(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_zone, key, value)
            
            db_zone.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(db_zone)
            return WeatherZone.model_validate(db_zone)

    async def delete(self, zone_id: UUID) -> bool:
        async with await self._get_session() as session:
            result = await session.execute(
                select(WeatherZoneModel).where(WeatherZoneModel.id == zone_id)
            )
            db_zone = result.scalar_one_or_none()
            if not db_zone:
                return False

            await session.delete(db_zone)
            await session.commit()
            return True

    async def get_by_coordinates(
        self,
        latitude: float,
        longitude: float,
        radius_km: float
    ) -> List[WeatherZone]:
        async with await self._get_session() as session:
            # Using the Haversine formula in SQL
            haversine = func.acos(
                func.sin(func.radians(latitude)) * func.sin(func.radians(WeatherZoneModel.center_latitude)) +
                func.cos(func.radians(latitude)) * func.cos(func.radians(WeatherZoneModel.center_latitude)) *
                func.cos(func.radians(longitude - WeatherZoneModel.center_longitude))
            ) * 6371  # Earth's radius in kilometers

            result = await session.execute(
                select(WeatherZoneModel).where(
                    and_(
                        WeatherZoneModel.is_active == True,
                        haversine <= radius_km
                    )
                )
            )
            db_zones = result.scalars().all()
            return [WeatherZone.model_validate(zone) for zone in db_zones]

    async def find_closest_zone(
        self,
        latitude: float,
        longitude: float,
        max_distance_km: float
    ) -> Optional[WeatherZone]:
        """
        Find the closest active zone within max_distance_km using Haversine formula.
        """
        async with await self._get_session() as session:
            # Using the Haversine formula in SQL
            haversine = func.acos(
                func.sin(func.radians(latitude)) * func.sin(func.radians(WeatherZoneModel.center_latitude)) +
                func.cos(func.radians(latitude)) * func.cos(func.radians(WeatherZoneModel.center_latitude)) *
                func.cos(func.radians(longitude - WeatherZoneModel.center_longitude))
            ) * 6371  # Earth's radius in kilometers

            result = await session.execute(
                select(WeatherZoneModel).where(
                    and_(
                        WeatherZoneModel.is_active == True,
                        haversine <= max_distance_km
                    )
                ).order_by(haversine)
            )
            db_zone = result.scalar_one_or_none()
            return WeatherZone.model_validate(db_zone) if db_zone else None

    async def count_zones_by_city(self, city: str) -> int:
        async with await self._get_session() as session:
            pattern = f"Zona {city}%"
            result = await session.execute(
                select(func.count()).select_from(WeatherZoneModel).where(WeatherZoneModel.name.like(pattern))
            )
            return result.scalar_one() 