import aiohttp
import asyncio
from typing import Dict, Optional
from datetime import datetime
import logging
import os

logger = logging.getLogger(__name__)

class OpenWeatherClient:
    """Cliente para OpenWeatherMap API - clima actual en tiempo real."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENWEATHER_API_KEY")
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.timeout = 10.0
        
        if not self.api_key:
            logger.warning("OpenWeatherMap API key not found. Set OPENWEATHER_API_KEY environment variable.")
    
    async def get_current_weather(self, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Obtiene el clima actual para coordenadas específicas.
        
        Returns:
            Dict con datos del clima actual o None si hay error
        """
        if not self.api_key:
            logger.error("OpenWeatherMap API key not configured")
            return None
        
        url = f"{self.base_url}/weather"
        params = {
            "lat": latitude,
            "lon": longitude,
            "appid": self.api_key,
            "units": "metric",  # Celsius, m/s, etc.
            "lang": "es"        # Español para descripciones
        }
        
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                logger.debug(f"Consultando OpenWeather para ({latitude:.4f}, {longitude:.4f})")
                
                async with session.get(url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()
                
                # Transformar respuesta de OpenWeather a nuestro formato
                current_weather = self._transform_response(data)
                
                logger.info(f"✅ Clima actual obtenido: {current_weather.get('temperature', 'N/A')}°C")
                return current_weather
                
        except aiohttp.ClientResponseError as e:
            if e.status == 401:
                logger.error("OpenWeatherMap API key inválida o expirada")
            elif e.status == 429:
                logger.warning("Rate limit excedido en OpenWeatherMap API")
            else:
                logger.error(f"Error HTTP {e.status} en OpenWeatherMap: {e.message}")
            return None
            
        except asyncio.TimeoutError:
            logger.error("Timeout consultando OpenWeatherMap API")
            return None
            
        except Exception as e:
            logger.error(f"Error inesperado en OpenWeatherMap: {type(e).__name__}: {e}")
            return None
    
    def _transform_response(self, data: Dict) -> Dict:
        """
        Transforma la respuesta de OpenWeatherMap a nuestro formato estándar.
        
        OpenWeather response structure:
        {
            "main": {"temp": 25.3, "humidity": 65, "pressure": 1013},
            "wind": {"speed": 3.2, "deg": 180},
            "weather": [{"description": "cielo claro"}],
            "visibility": 10000,
            "dt": 1640995200
        }
        """
        try:
            main = data.get("main", {})
            wind = data.get("wind", {})
            weather_list = data.get("weather", [{}])
            weather_desc = weather_list[0].get("description", "") if weather_list else ""
            
            # Convertir timestamp Unix a datetime
            timestamp = datetime.fromtimestamp(data.get("dt", 0))
            
            current_weather = {
                "temperature": round(main.get("temp", 0.0), 1),
                "humidity": main.get("humidity", 0),
                "pressure": main.get("pressure", 0),
                "wind_speed": round(wind.get("speed", 0.0), 1),
                "wind_direction": wind.get("deg", 0),
                "visibility": data.get("visibility", 0) / 1000,  # Convertir m a km
                "description": weather_desc,
                "timestamp": timestamp,
                "source": "openweather"
            }
            
            # Agregar datos adicionales si están disponibles
            if "rain" in data:
                current_weather["precipitation"] = data["rain"].get("1h", 0.0)
            else:
                current_weather["precipitation"] = 0.0
            
            # Calcular sensación térmica si está disponible
            if "feels_like" in main:
                current_weather["feels_like"] = round(main["feels_like"], 1)
            
            logger.debug(f"Datos transformados: {current_weather}")
            return current_weather
            
        except Exception as e:
            logger.error(f"Error transformando respuesta de OpenWeather: {e}")
            return {}
    
    async def health_check(self) -> bool:
        """
        Verifica si la API de OpenWeatherMap está disponible.
        
        Returns:
            True si la API responde correctamente
        """
        if not self.api_key:
            return False
        
        # Usar coordenadas de Buenos Aires para test
        test_lat, test_lon = -34.6037, -58.3816
        
        try:
            result = await self.get_current_weather(test_lat, test_lon)
            return result is not None
        except Exception:
            return False 