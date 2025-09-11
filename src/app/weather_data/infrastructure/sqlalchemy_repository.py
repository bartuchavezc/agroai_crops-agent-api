from sqlalchemy import select, and_, desc
from typing import List, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ..domain.entities import WeatherData
from .entities.weather_measurements import weather_measurements_table
from ..domain.repositories import WeatherRepository
import logging

logger = logging.getLogger(__name__)

class SQLAlchemyRepository(WeatherRepository):
    """PostgreSQL repository for weather data using SQLAlchemy."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def save(self, weather_data: WeatherData) -> WeatherData:
        """Save weather data to PostgreSQL."""
        async with self.session_factory() as session:
            async with session.begin():
                # Insert data into PostgreSQL
                insert_stmt = weather_measurements_table.insert().values(
                    timestamp=weather_data.timestamp,
                    latitude=weather_data.latitude,
                    longitude=weather_data.longitude,
                    temperature=weather_data.temperature,
                    humidity=weather_data.humidity,
                    precipitation=weather_data.precipitation,
                    wind_speed=weather_data.wind_speed,
                    wind_direction=weather_data.wind_direction,
                    pressure=weather_data.pressure,
                    soil_moisture=weather_data.soil_moisture
                )
                
                result = await session.execute(insert_stmt)
                
                # Set the generated ID
                weather_data.id = result.inserted_primary_key[0]
                logger.debug(f"Saved weather data to PostgreSQL with ID: {weather_data.id}")
                return weather_data

    async def save_batch(self, weather_data_list: List[WeatherData]) -> List[WeatherData]:
        """Save multiple weather data records to PostgreSQL."""
        if not weather_data_list:
            return []

        async with self.session_factory() as session:
            async with session.begin():
                # Prepare batch insert data
                insert_data = []
                for weather_data in weather_data_list:
                    insert_data.append({
                        'timestamp': weather_data.timestamp,
                        'latitude': weather_data.latitude,
                        'longitude': weather_data.longitude,
                        'temperature': weather_data.temperature,
                        'humidity': weather_data.humidity,
                        'precipitation': weather_data.precipitation,
                        'wind_speed': weather_data.wind_speed,
                        'wind_direction': weather_data.wind_direction,
                        'pressure': weather_data.pressure,
                        'soil_moisture': weather_data.soil_moisture
                    })

                # Bulk insert
                await session.execute(
                    weather_measurements_table.insert(),
                    insert_data
                )
                
                logger.info(f"Saved {len(weather_data_list)} weather records to PostgreSQL")
                return weather_data_list

    async def find_by_location_and_time_range(
        self,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000
    ) -> List[WeatherData]:
        """Find weather data by location and time range."""
        async with self.session_factory() as session:
            stmt = select(weather_measurements_table).where(
                and_(
                    weather_measurements_table.c.latitude == latitude,
                    weather_measurements_table.c.longitude == longitude,
                    weather_measurements_table.c.timestamp >= start_time,
                    weather_measurements_table.c.timestamp <= end_time
                )
            ).order_by(weather_measurements_table.c.timestamp).limit(limit)
            
            result = await session.execute(stmt)
            rows = result.fetchall()
            
            weather_data_list = []
            for row in rows:
                weather_data_list.append(WeatherData(
                    id=row.id,
                    timestamp=row.timestamp,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.temperature,
                    humidity=row.humidity,
                    precipitation=row.precipitation,
                    wind_speed=row.wind_speed,
                    wind_direction=row.wind_direction,
                    pressure=row.pressure,
                    soil_moisture=row.soil_moisture
                ))
            
            logger.debug(f"Found {len(weather_data_list)} weather records in PostgreSQL")
            return weather_data_list

    async def find_latest_by_location(
        self, 
        latitude: float, 
        longitude: float, 
        limit: int = 10
    ) -> List[WeatherData]:
        """Find latest weather data for a specific location."""
        async with self.session_factory() as session:
            stmt = select(weather_measurements_table).where(
                and_(
                    weather_measurements_table.c.latitude == latitude,
                    weather_measurements_table.c.longitude == longitude
                )
            ).order_by(desc(weather_measurements_table.c.timestamp)).limit(limit)
            
            result = await session.execute(stmt)
            rows = result.fetchall()
            
            weather_data_list = []
            for row in rows:
                weather_data_list.append(WeatherData(
                    id=row.id,
                    timestamp=row.timestamp,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.temperature,
                    humidity=row.humidity,
                    precipitation=row.precipitation,
                    wind_speed=row.wind_speed,
                    wind_direction=row.wind_direction,
                    pressure=row.pressure,
                    soil_moisture=row.soil_moisture
                ))
            
            return weather_data_list

    async def find_recent(self, hours: int = 24) -> List[WeatherData]:
        """Find recent weather data within specified hours."""
        async with self.session_factory() as session:
            from sqlalchemy import text
            
            stmt = select(weather_measurements_table).where(
                text(f"timestamp >= NOW() - INTERVAL '{hours} hours'")
            ).order_by(desc(weather_measurements_table.c.timestamp))
            
            result = await session.execute(stmt)
            rows = result.fetchall()
            
            weather_data_list = []
            for row in rows:
                weather_data_list.append(WeatherData(
                    id=row.id,
                    timestamp=row.timestamp,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.temperature,
                    humidity=row.humidity,
                    precipitation=row.precipitation,
                    wind_speed=row.wind_speed,
                    wind_direction=row.wind_direction,
                    pressure=row.pressure,
                    soil_moisture=row.soil_moisture
                ))
            
            logger.debug(f"Found {len(weather_data_list)} recent weather records in PostgreSQL")
            return weather_data_list

    async def add(self, weather_data: WeatherData) -> WeatherData:
        """Add (save) weather data to PostgreSQL."""
        return await self.save(weather_data)
    
    async def get(self, id: int) -> Optional[WeatherData]:
        """Get weather data by ID."""
        async with self.session_factory() as session:
            stmt = select(weather_measurements_table).where(weather_measurements_table.c.id == id)
            result = await session.execute(stmt)
            row = result.fetchone()
            
            if row:
                return WeatherData(
                    id=row.id,
                    timestamp=row.timestamp,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.temperature,
                    humidity=row.humidity,
                    precipitation=row.precipitation,
                    wind_speed=row.wind_speed,
                    wind_direction=row.wind_direction,
                    pressure=row.pressure,
                    soil_moisture=row.soil_moisture
                )
            return None
    
    async def list(self) -> List[WeatherData]:
        """List all weather data."""
        async with self.session_factory() as session:
            stmt = select(weather_measurements_table).order_by(desc(weather_measurements_table.c.timestamp)).limit(100)
            result = await session.execute(stmt)
            rows = result.fetchall()
            
            weather_data_list = []
            for row in rows:
                weather_data_list.append(WeatherData(
                    id=row.id,
                    timestamp=row.timestamp,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.temperature,
                    humidity=row.humidity,
                    precipitation=row.precipitation,
                    wind_speed=row.wind_speed,
                    wind_direction=row.wind_direction,
                    pressure=row.pressure,
                    soil_moisture=row.soil_moisture
                ))
            return weather_data_list
    
    async def get_by_location(self, 
                            latitude: float, 
                            longitude: float,
                            start_time: datetime,
                            end_time: datetime) -> List[WeatherData]:
        """Get weather data by location and time range."""
        return await self.find_by_location_and_time_range(latitude, longitude, start_time, end_time)
    
    async def get_latest(self, 
                        latitude: float, 
                        longitude: float) -> Optional[WeatherData]:
        """Get latest weather data for a location."""
        latest_data = await self.find_latest_by_location(latitude, longitude, limit=1)
        return latest_data[0] if latest_data else None 