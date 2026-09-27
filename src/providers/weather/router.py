from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query

from src.auth.api.dependencies import get_current_user

from .service import WeatherService

router = APIRouter(prefix="/weather", tags=["Weather"], dependencies=[Depends(get_current_user)])

WEATHER = Provide["data_providers.weather_service"]
LAT = Query(..., ge=-90, le=90)
LON = Query(..., ge=-180, le=180)


@router.get("/current", summary="Current weather (OpenWeather, cached 15 min)")
@inject
async def current_weather(latitude: float = LAT, longitude: float = LON, weather: WeatherService = Depends(WEATHER)):
    data = await weather.current(latitude, longitude)
    if not data:
        raise HTTPException(status_code=404, detail="Could not get current weather")
    return {"success": True, "data": data, "source": "openweather", "cache_ttl_minutes": 15}


@router.get("/current/health", summary="OpenWeather health")
@inject
async def current_weather_health(weather: WeatherService = Depends(WEATHER)):
    return await weather.health()


@router.get("/latest", summary="Latest stored observation")
@inject
async def latest_weather(latitude: float = LAT, longitude: float = LON, weather: WeatherService = Depends(WEATHER)):
    history = await weather.history(latitude, longitude, hours_back=24)
    if not history:
        raise HTTPException(status_code=404, detail="No weather data found")
    return history[-1]


@router.get("/history", summary="Stored observations")
@inject
async def weather_history(
    latitude: float = LAT,
    longitude: float = LON,
    hours_back: int = Query(24, ge=1, le=24 * 90),
    weather: WeatherService = Depends(WEATHER),
):
    data = await weather.history(latitude, longitude, hours_back)
    return {"count": len(data), "data": data}


@router.get("/forecast", summary="SMN forecast (daily summary + hourly series)")
@inject
async def weather_forecast(
    latitude: float = LAT,
    longitude: float = LON,
    days: int = Query(3, ge=1, le=4),
    weather: WeatherService = Depends(WEATHER),
):
    daily = await weather.daily_forecast(latitude, longitude, days)
    hourly = await weather.forecast_rows(latitude, longitude, hours=days * 24, resolution="1h")
    return {
        "source": "smn_wrf",
        "issued_at": max((r.issued_at for r in hourly), default=None),
        "daily": [d.to_dict() for d in daily],
        "hourly": [
            {
                "time": r.time.isoformat(),
                "temperature": r.temperature,
                "humidity": r.humidity,
                "precipitation_accum": r.precipitation_accum,
                "wind_speed": r.wind_speed,
            }
            for r in hourly
        ],
    }
