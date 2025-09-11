from sqlalchemy import text
from typing import List
from datetime import datetime
from ..domain.entities import WeatherData
from .entities.timescale_weather_series import (
    WeatherAggregation,
    ChunkInfo,
    TimescaleQueries,
    TimescaleWeatherSeries,
    weather_timeseries_table,
    weather_timeseries_id_seq
)
from ..domain.repositories import TimeseriesWeatherRepository
from src.app.timeseries import get_timescale_db_session
import logging
from sqlalchemy import select

logger = logging.getLogger(__name__)

class TimeseriesRepository(TimeseriesWeatherRepository):
    """TimescaleDB optimized repository for weather data time series storage with advanced features."""

    async def save_batch(self, weather_data_list: List[WeatherData]) -> List[WeatherData]:
        """Save multiple weather data records optimized for time series."""
        if not weather_data_list:
            return []

        async with get_timescale_db_session() as session:
            # Convert to TimescaleDB entities for optimization
            timescale_series_list = [
                TimescaleWeatherSeries.from_weather_data(wd) for wd in weather_data_list
            ]
            
            # Use SQLAlchemy with the timescale table for bulk insert
            insert_data = []
            for series in timescale_series_list:
                insert_dict = series.to_insert_dict()
                # Generate ID using sequence if not provided
                if 'id' not in insert_dict or insert_dict['id'] is None:
                    insert_dict['id'] = await session.execute(weather_timeseries_id_seq.next_value())
                    insert_dict['id'] = insert_dict['id'].scalar()
                insert_data.append(insert_dict)
            
            # Execute batch insert using SQLAlchemy table
            await session.execute(weather_timeseries_table.insert(), insert_data)
            
            logger.info(f"Saved {len(weather_data_list)} weather records to TimescaleDB hypertable")
            return weather_data_list

    async def find_by_location_and_time_range(
        self,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000
    ) -> List[WeatherData]:
        """Find weather data by location and time range with TimescaleDB time-series optimizations."""
        async with get_timescale_db_session() as session:
            # Use SQLAlchemy with TimescaleDB table
            stmt = select(weather_timeseries_table).where(
                (weather_timeseries_table.c.latitude == latitude) &
                (weather_timeseries_table.c.longitude == longitude) &
                (weather_timeseries_table.c.timestamp >= start_time) &
                (weather_timeseries_table.c.timestamp <= end_time)
            ).order_by(weather_timeseries_table.c.timestamp).limit(limit)
            
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
            
            logger.debug(f"Found {len(weather_data_list)} weather records in TimescaleDB")
            return weather_data_list

    async def find_recent(self, hours: int = 24) -> List[WeatherData]:
        """Find recent weather data using TimescaleDB time functions."""
        async with get_timescale_db_session() as session:
            # Use TimescaleDB time functions with SQLAlchemy
            stmt = select(weather_timeseries_table).where(
                text(f"timestamp >= NOW() - INTERVAL '{hours} hours'")
            ).order_by(weather_timeseries_table.c.timestamp.desc())
            
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
            
            logger.debug(f"Found {len(weather_data_list)} recent weather records in TimescaleDB")
            return weather_data_list

    async def delete_old_data(self, days: int = 1825) -> int:
        """Delete old weather data using TimescaleDB retention policies."""
        async with get_timescale_db_session() as session:
            # Use TimescaleDB efficient deletion
            query = f"""
                DELETE FROM weather_timeseries
                WHERE timestamp < NOW() - INTERVAL '{days} days'
            """
            
            result = await session.execute(text(query))
            
            deleted_count = result.rowcount
            logger.info(f"Deleted {deleted_count} old weather records from TimescaleDB")
            return deleted_count

    # Advanced TimescaleDB specific methods
    async def get_aggregated_data(
        self,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
        bucket_size: str = "1 hour"
    ) -> List[WeatherAggregation]:
        """Get aggregated weather data using TimescaleDB time_bucket function."""
        async with get_timescale_db_session() as session:
            query = TimescaleQueries.time_bucket_aggregate(bucket_size)
            
            result = await session.execute(
                text(query),
                {
                    "start_time": start_time,
                    "end_time": end_time,
                    "latitude": latitude,
                    "longitude": longitude
                }
            )
            
            aggregations = []
            for row in result.fetchall():
                aggregations.append(WeatherAggregation(
                    time_bucket=row.time_bucket,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    avg_temperature=row.avg_temperature,
                    min_temperature=row.min_temperature,
                    max_temperature=row.max_temperature,
                    avg_humidity=row.avg_humidity,
                    total_precipitation=row.total_precipitation,
                    avg_wind_speed=row.avg_wind_speed,
                    avg_pressure=row.avg_pressure,
                    data_count=row.data_count,
                    bucket_size=bucket_size
                ))
            
            logger.debug(f"Generated {len(aggregations)} aggregated buckets for {bucket_size}")
            return aggregations

    async def get_latest_by_all_locations(self) -> List[WeatherData]:
        """Get latest weather data for all locations using TimescaleDB last() function."""
        async with get_timescale_db_session() as session:
            query = TimescaleQueries.latest_data_by_location()
            
            result = await session.execute(text(query))
            
            weather_data_list = []
            for row in result.fetchall():
                weather_data_list.append(WeatherData(
                    latitude=row.latitude,
                    longitude=row.longitude,
                    temperature=row.latest_temperature,
                    humidity=row.latest_humidity,
                    precipitation=row.latest_precipitation,
                    wind_speed=row.latest_wind_speed,
                    wind_direction=row.latest_wind_direction,
                    pressure=row.latest_pressure,
                    soil_moisture=row.latest_soil_moisture,
                    timestamp=row.latest_timestamp
                ))
            
            logger.debug(f"Found latest data for {len(weather_data_list)} locations")
            return weather_data_list

    async def get_chunk_info(self) -> List[ChunkInfo]:
        """Get TimescaleDB chunk information for monitoring."""
        async with get_timescale_db_session() as session:
            query = TimescaleQueries.get_chunk_info()
            
            result = await session.execute(text(query))
            
            chunks = []
            for row in result.fetchall():
                chunks.append(ChunkInfo(
                    chunk_name=row.chunk_name,
                    chunk_schema=row.chunk_schema,
                    table_name=row.table_name,
                    range_start=row.range_start,
                    range_end=row.range_end,
                    is_compressed=row.is_compressed,
                    chunk_size=row.chunk_size
                ))
            
            return chunks

    async def compress_old_chunks(self, days: int = 7) -> int:
        """Manually compress chunks older than specified days."""
        async with get_timescale_db_session() as session:
            query = TimescaleQueries.compress_chunks_older_than(days)
            
            result = await session.execute(text(query))
            compressed_chunks = result.fetchall()
            
            await session.commit()
            
            compressed_count = len(compressed_chunks)
            logger.info(f"Compressed {compressed_count} chunks older than {days} days")
            return compressed_count

    async def get_weather_statistics(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> List[dict]:
        """Get weather statistics summary using TimescaleDB aggregation functions."""
        async with get_timescale_db_session() as session:
            query = TimescaleQueries.weather_stats_summary()
            
            result = await session.execute(
                text(query),
                {"start_time": start_time, "end_time": end_time}
            )
            
            stats = []
            for row in result.fetchall():
                stats.append({
                    "latitude": row.latitude,
                    "longitude": row.longitude,
                    "first_reading": row.first_reading,
                    "last_reading": row.last_reading,
                    "total_readings": row.total_readings,
                    "avg_temperature": row.avg_temperature,
                    "temp_stddev": row.temp_stddev,
                    "avg_humidity": row.avg_humidity,
                    "total_precipitation": row.total_precipitation,
                    "avg_wind_speed": row.avg_wind_speed
                })
            
            return stats

    async def store_time_series(self, data: WeatherData):
        """Store weather data in TimescaleDB time series."""
        return await self.save_batch([data])
    
    async def get_time_series(self, latitude: float, longitude: float, start_time: datetime, end_time: datetime) -> List[WeatherData]:
        """Get time series weather data from TimescaleDB."""
        return await self.find_by_location_and_time_range(latitude, longitude, start_time, end_time) 