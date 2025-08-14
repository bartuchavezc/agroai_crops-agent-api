from sqlalchemy import Table, Column, Integer, Float, DateTime, Index
from src.app.database import shared_metadata

# SQLAlchemy Table definition for weather measurements
weather_measurements_table = Table(
    'weather_measurements',
    shared_metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('timestamp', DateTime, nullable=False, index=True),
    Column('latitude', Float, nullable=False, index=True),
    Column('longitude', Float, nullable=False, index=True),
    Column('temperature', Float, nullable=False),
    Column('humidity', Float, nullable=False),
    Column('precipitation', Float, nullable=False),
    Column('wind_speed', Float, nullable=False),
    Column('wind_direction', Float, nullable=False),
    Column('pressure', Float, nullable=False),
    Column('soil_moisture', Float, nullable=True),
    Index('idx_weather_location', 'latitude', 'longitude'),
    Index('idx_weather_time', 'timestamp'),
) 