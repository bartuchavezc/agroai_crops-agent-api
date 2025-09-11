from fastapi import APIRouter, Depends, HTTPException, Request, Query
from typing import List, Optional
from datetime import datetime, timedelta

from src.app.weather_data.service.weather_service import WeatherService
from src.app.weather_data.service.weather_batch_service import WeatherBatchService
from src.app.weather_data.service.current_weather_service import CurrentWeatherService

router = APIRouter(prefix="/weather", tags=["weather"])

def get_weather_service(request: Request) -> WeatherService:
    container = request.app.state.container
    return container.weather_data.weather_service()

def get_weather_batch_service(request: Request) -> WeatherBatchService:
    container = request.app.state.container
    return container.weather_data.weather_batch_service()

def get_current_weather_service(request: Request) -> CurrentWeatherService:
    container = request.app.state.container
    return container.weather_data.current_weather_service()

@router.get("/latest")
async def get_latest_weather(
    latitude: float,
    longitude: float,
    weather_service: WeatherService = Depends(get_weather_service)
):
    """Obtiene los datos meteorológicos más recientes para una ubicación."""
    try:
        data = await weather_service.get_latest_weather(latitude, longitude)
        if not data:
            raise HTTPException(status_code=404, detail="No weather data found")
        return data.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/fetch")
async def fetch_weather_data(
    target_date: Optional[str] = Query(None, description="Fecha específica en formato YYYY-MM-DD (opcional, por defecto usa fecha actual)"),
    weather_batch_service: WeatherBatchService = Depends(get_weather_batch_service)
):
    """Obtiene datos meteorológicos para todas las zonas activas usando el batch service optimizado."""
    try:
        # Parsear fecha si se proporciona, sino usar fecha actual
        if target_date:
            try:
                parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
        else:
            parsed_date = datetime.now()
        
        # Usar el batch service directamente
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/current")
async def get_current_weather(
    latitude: float,
    longitude: float,
    current_weather_service: CurrentWeatherService = Depends(get_current_weather_service)
):
    """Obtiene el clima actual en tiempo real para una ubicación específica (OpenWeatherMap)."""
    try:
        data = await current_weather_service.get_current_weather(latitude, longitude)
        if not data:
            raise HTTPException(status_code=404, detail="No se pudo obtener el clima actual")
        
        return {
            "success": True,
            "data": data.to_dict(),
            "source": "openweather",
            "cache_ttl_minutes": 15
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/current/health")
async def current_weather_health_check(
    current_weather_service: CurrentWeatherService = Depends(get_current_weather_service)
):
    """Verifica el estado del servicio de clima actual."""
    try:
        health_status = await current_weather_service.health_check()
        return health_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/history")
async def get_weather_history(
    latitude: float,
    longitude: float,
    hours_back: int = 24,
    weather_service: WeatherService = Depends(get_weather_service)
):
    """Obtiene el historial de datos meteorológicos."""
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