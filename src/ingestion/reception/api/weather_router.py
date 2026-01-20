# src/ingestion/reception/api/weather_router.py
"""
Weather data reception endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter(prefix="/weather", tags=["Weather Ingestion"])


def get_weather_service(request: Request):
    """Get weather service from container."""
    container = request.app.state.container
    return container.ingestion.weather_service()


def get_weather_batch_service(request: Request):
    """Get weather batch service from container."""
    container = request.app.state.container
    return container.ingestion.weather_batch_service()


def get_current_weather_service(request: Request):
    """Get current weather service from container."""
    container = request.app.state.container
    return container.ingestion.current_weather_service()


@router.get("/latest", summary="Get Latest Weather")
async def get_latest_weather(
    latitude: float,
    longitude: float,
    weather_service = Depends(get_weather_service)
):
    """
    Get the most recent weather data for a location.
    """
    try:
        data = await weather_service.get_latest_weather(latitude, longitude)
        if not data:
            raise HTTPException(status_code=404, detail="No weather data found")
        return data.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fetch", summary="Fetch Weather Data")
async def fetch_weather_data(
    target_date: Optional[str] = Query(
        None, 
        description="Target date in YYYY-MM-DD format (optional, defaults to current date)"
    ),
    weather_batch_service = Depends(get_weather_batch_service)
):
    """
    Fetch weather data for all active zones using optimized batch service.
    """
    try:
        if target_date:
            try:
                parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        else:
            parsed_date = datetime.now()
        
        result = await weather_batch_service.populate_all_zones_weather(parsed_date)
        
        return {
            "message": "Weather data fetched successfully",
            "target_date": parsed_date.strftime("%Y-%m-%d"),
            "zones_processed": result.get("zones_processed", 0),
            "storage_results": {
                "postgresql": result.get("stored", 0),
                "redis_cache": result.get("cached", 0),
                "timescaledb": result.get("timeseries", 0)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", summary="Get Current Weather")
async def get_current_weather(
    latitude: float,
    longitude: float,
    current_weather_service = Depends(get_current_weather_service)
):
    """
    Get real-time current weather for a specific location (OpenWeatherMap).
    """
    try:
        data = await current_weather_service.get_current_weather(latitude, longitude)
        if not data:
            raise HTTPException(status_code=404, detail="Could not get current weather")
        
        return {
            "success": True,
            "data": data.to_dict(),
            "source": "openweather",
            "cache_ttl_minutes": 15
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current/health", summary="Current Weather Health Check")
async def current_weather_health_check(
    current_weather_service = Depends(get_current_weather_service)
):
    """
    Check the health of the current weather service.
    """
    try:
        health_status = await current_weather_service.health_check()
        return health_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", summary="Get Weather History")
async def get_weather_history(
    latitude: float,
    longitude: float,
    hours_back: int = 24,
    weather_service = Depends(get_weather_service)
):
    """
    Get historical weather data for a location.
    """
    try:
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours_back)
        
        data = await weather_service.get_weather_history(
            latitude, longitude, start_time, end_time
        )
        
        return {
            "count": len(data),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "data": [item.to_dict() for item in data]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
