import s3fs
import xarray as xr
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import logging
import numpy as np

logger = logging.getLogger(__name__)

class SMNClient:
    def __init__(self):
        self.s3_client = s3fs.S3FileSystem(anon=True)
        self.base_path = "smn-ar-wrf"
        self._cached_dataset = None
        self._cached_path = None
    
    def _get_smn_forecast_cycle(self, current_time: datetime) -> tuple[datetime, int]:
        """
        SMN oficial: Solo 2 ciclos por día (00 UTC y 12 UTC)
        Lógica: UTC >= 12 → usar 12 UTC, sino → usar 00 UTC
        """
        # Argentina UTC-3: sumar 3 horas
        utc_time = current_time + timedelta(hours=3)
        utc_hour = utc_time.hour
        
        # SMN solo tiene 2 ciclos oficiales
        if utc_hour >= 12:
            smn_hour = 12
            target_date = current_time
        elif utc_hour >= 6:  # Entre 06-11 UTC, usar 00 UTC del mismo día
            smn_hour = 0
            target_date = current_time
        else:  # Antes de 06 UTC, usar 00 UTC del día anterior
            smn_hour = 0
            target_date = current_time - timedelta(days=1)
        
        logger.info(f"Hora {current_time.hour:02d}:00 ARG → {utc_hour:02d}:00 UTC → usar SMN ciclo {smn_hour:02d} UTC")
        
        return target_date.replace(minute=0, second=0, microsecond=0), smn_hour
    
    def _build_path(self, cycle_date: datetime, target_hour: int, frequency: str = "01H") -> str:
        """
        Construye path simple: usa la fecha actual y la hora UTC calculada
        """
        return (
            f"{self.base_path}/DATA/WRF/DET/"
            f"{cycle_date.year:04d}/{cycle_date.month:02d}/{cycle_date.day:02d}/"
            f"{target_hour:02d}/WRFDETAR_{frequency}_{cycle_date.strftime('%Y%m%d')}_"
            f"{target_hour:02d}_000.nc"
        )
    
    def _lat_lon_to_grid_coords(self, lat: float, lon: float, dataset: xr.Dataset) -> tuple[int, int]:
        """
        Convierte coordenadas geográficas (lat, lon) a coordenadas del grid SMN (y, x).
        
        Los archivos SMN WRF usan una proyección Lambert Conformal Conic sobre Argentina.
        Aproximación simple basada en los límites típicos del dominio SMN:
        - Latitud: -55° a -21° (Sur a Norte)
        - Longitud: -73° a -53° (Oeste a Este)
        """
        try:
            # Límites aproximados del dominio SMN Argentina
            lat_min, lat_max = -55.0, -21.0  # Sur a Norte
            lon_min, lon_max = -73.0, -53.0  # Oeste a Este
            
            # Obtener dimensiones del grid
            ny = dataset.sizes['y']
            nx = dataset.sizes['x']
            
            # Asegurar que las coordenadas están dentro del dominio
            lat_clipped = np.clip(lat, lat_min, lat_max)
            lon_clipped = np.clip(lon, lon_min, lon_max)
            
            # Conversión lineal a coordenadas del grid
            # y: latitud (0 = Sur, ny-1 = Norte)
            y_grid = int((lat_clipped - lat_min) / (lat_max - lat_min) * (ny - 1))
            
            # x: longitud (0 = Oeste, nx-1 = Este) 
            x_grid = int((lon_clipped - lon_min) / (lon_max - lon_min) * (nx - 1))
            
            # Asegurar que estén dentro de los límites del grid
            y_grid = np.clip(y_grid, 0, ny - 1)
            x_grid = np.clip(x_grid, 0, nx - 1)
            
            logger.debug(f"Coordenadas geográficas ({lat:.4f}, {lon:.4f}) → Grid ({y_grid}, {x_grid})")
            return y_grid, x_grid
            
        except Exception as e:
            logger.error(f"Error convirtiendo coordenadas: {e}")
            # Fallback al centro si hay error
            y_center = dataset.sizes['y'] // 2
            x_center = dataset.sizes['x'] // 2
            logger.warning(f"Usando coordenadas del centro como fallback: ({y_center}, {x_center})")
            return y_center, x_center
    
    async def get_forecast(self, 
                          date: datetime, 
                          latitude: Optional[float] = None,
                          longitude: Optional[float] = None,
                          frequency: str = "01H") -> Optional[Dict]:
        """
        Obtiene pronóstico del SMN usando los 2 ciclos oficiales (00 UTC y 12 UTC)
        para coordenadas específicas.
        """
        try:
            cycle_date, smn_hour = self._get_smn_forecast_cycle(date)
            
            # Intentar con el ciclo calculado primero
            path = self._build_path(cycle_date, smn_hour, frequency)
            logger.info(f"Buscando datos SMN en: {path}")
            
            try:
                with self.s3_client.open(path) as f:
                    dataset = xr.open_dataset(f)
                    logger.debug(f"Dataset abierto. Variables: {list(dataset.data_vars.keys())}")
                    logger.debug(f"Dimensiones: {dataset.dims}")
                    result = self._process_dataset(dataset, latitude, longitude)
                    logger.info(f"✅ Datos SMN obtenidos exitosamente para ciclo {smn_hour:02d} UTC")
                    return result
            except Exception as e:
                logger.error(f"Error detallado para ciclo {smn_hour:02d} UTC: {type(e).__name__}: {e}")
                
                # Fallback: intentar con el otro ciclo oficial
                fallback_hour = 0 if smn_hour == 12 else 12
                fallback_date = cycle_date if smn_hour == 12 else cycle_date - timedelta(days=1)
                
                fallback_path = self._build_path(fallback_date, fallback_hour, frequency)
                logger.info(f"Probando fallback en: {fallback_path}")
                
                try:
                    with self.s3_client.open(fallback_path) as f:
                        dataset = xr.open_dataset(f)
                        logger.debug(f"Dataset fallback abierto. Variables: {list(dataset.data_vars.keys())}")
                        logger.debug(f"Dimensiones fallback: {dataset.dims}")
                        result = self._process_dataset(dataset, latitude, longitude)
                        logger.info(f"✅ Datos SMN obtenidos con fallback ciclo {fallback_hour:02d} UTC")
                        return result
                except Exception as fallback_error:
                    logger.error(f"Fallback también falló: {type(fallback_error).__name__}: {fallback_error}")
                    
        except Exception as e:
            logger.error(f"❌ Error obteniendo datos SMN: {e}")
            return None
    
    def _process_dataset(self, dataset: xr.Dataset, latitude: Optional[float] = None, longitude: Optional[float] = None) -> Dict:
        """
        Procesa el dataset de xarray extrayendo datos del punto específico solicitado
        """
        try:
            # Si se proporcionan coordenadas, usarlas; sino usar el centro
            if latitude is not None and longitude is not None:
                y_grid, x_grid = self._lat_lon_to_grid_coords(latitude, longitude, dataset)
                logger.debug(f"Extrayendo datos para coordenadas ({latitude:.4f}, {longitude:.4f}) → Grid ({y_grid}, {x_grid})")
            else:
                # Fallback al punto central
                y_grid = dataset.sizes['y'] // 2
                x_grid = dataset.sizes['x'] // 2
                logger.debug(f"Extrayendo datos del punto central: y={y_grid}, x={x_grid}")
            
            result = {
                "temperature": float(dataset.T2.isel(time=0, y=y_grid, x=x_grid).values),
                "humidity": float(dataset.HR2.isel(time=0, y=y_grid, x=x_grid).values),
                "precipitation": float(dataset.PP.isel(time=0, y=y_grid, x=x_grid).values),
                "wind_speed": float(dataset.magViento10.isel(time=0, y=y_grid, x=x_grid).values),
                "wind_direction": float(dataset.dirViento10.isel(time=0, y=y_grid, x=x_grid).values),
                "pressure": float(dataset.PSFC.isel(time=0, y=y_grid, x=x_grid).values),
                "soil_moisture": float(dataset.SMOIS.isel(time=0, y=y_grid, x=x_grid).values) if 'SMOIS' in dataset else None
            }
            
            logger.debug(f"Datos procesados exitosamente: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error procesando dataset: {type(e).__name__}: {e}")
            raise e 

    async def get_forecast_batch(self, 
                               coordinates: List[Tuple[float, float]], 
                               date: datetime, 
                               frequency: str = "01H") -> List[Optional[Dict]]:
        """
        Obtiene pronóstico del SMN para múltiples coordenadas usando el mismo dataset.
        Optimizado para reducir descargas repetidas del mismo archivo NetCDF.
        
        Args:
            coordinates: Lista de tuplas (latitude, longitude)
            date: Fecha objetivo
            frequency: Frecuencia de datos (por defecto "01H")
            
        Returns:
            Lista de diccionarios con datos meteorológicos (o None si falla)
        """
        try:
            cycle_date, smn_hour = self._get_smn_forecast_cycle(date)
            path = self._build_path(cycle_date, smn_hour, frequency)
            
            logger.info(f"🚀 Batch fetch para {len(coordinates)} coordenadas desde: {path}")
            
            # Intentar con el ciclo calculado primero
            dataset = await self._get_dataset_cached(path)
            if dataset is not None:
                return self._process_dataset_batch(dataset, coordinates)
            
            # Fallback: intentar con el otro ciclo oficial
            fallback_hour = 0 if smn_hour == 12 else 12
            fallback_date = cycle_date if smn_hour == 12 else cycle_date - timedelta(days=1)
            fallback_path = self._build_path(fallback_date, fallback_hour, frequency)
            
            logger.info(f"🔄 Probando fallback batch: {fallback_path}")
            dataset = await self._get_dataset_cached(fallback_path)
            if dataset is not None:
                logger.info(f"✅ Batch fetch completado con fallback ciclo {fallback_hour:02d} UTC")
                return self._process_dataset_batch(dataset, coordinates)
            
            logger.error("❌ Fallback batch también falló")
            return [None] * len(coordinates)
            
        except Exception as e:
            logger.error(f"❌ Error en batch fetch: {e}")
            return [None] * len(coordinates)
    
    async def _get_dataset_cached(self, path: str) -> Optional[xr.Dataset]:
        """
        Obtiene el dataset NetCDF con cache simple para evitar descargas repetidas.
        Carga datos en memoria para evitar problemas de archivos cerrados.
        """
        try:
            # Si ya tenemos este dataset en cache, reutilizarlo
            if self._cached_path == path and self._cached_dataset is not None:
                logger.debug(f"📋 Usando dataset en cache: {path}")
                return self._cached_dataset
            
            # Descargar nuevo dataset y cargarlo en memoria
            logger.debug(f"📥 Descargando nuevo dataset: {path}")
            with self.s3_client.open(path) as f:
                dataset = xr.open_dataset(f)
                
                # IMPORTANTE: Cargar datos en memoria para evitar problemas de archivo cerrado
                dataset = dataset.load()
                
                # Cachear para reutilización
                self._cached_dataset = dataset
                self._cached_path = path
                
                logger.debug(f"Dataset cacheado en memoria. Variables: {list(dataset.data_vars.keys())}")
                logger.debug(f"Dimensiones: {dataset.dims}")
                return dataset
                
        except Exception as e:
            logger.error(f"Error obteniendo dataset {path}: {type(e).__name__}: {e}")
            return None
    
    def _process_dataset_batch(self, dataset: xr.Dataset, coordinates: List[Tuple[float, float]]) -> List[Optional[Dict]]:
        """
        Procesa múltiples coordenadas desde el mismo dataset usando operaciones vectorizadas.
        Optimizado como pandas: extrae todos los datos de una vez sin bucle.
        """
        if not coordinates:
            return []
        
        dataset_dims = f"y={dataset.sizes['y']}, x={dataset.sizes['x']}"
        logger.debug(f"📊 Procesando {len(coordinates)} coordenadas vectorizadas en dataset ({dataset_dims})")
        
        try:
            # 1. Convertir todas las coordenadas geográficas a coordenadas de grid vectorizadamente
            y_grids = []
            x_grids = []
            
            for latitude, longitude in coordinates:
                y_grid, x_grid = self._lat_lon_to_grid_coords(latitude, longitude, dataset)
                y_grids.append(y_grid)
                x_grids.append(x_grid)
            
            variables_map = {
                'temperature': 'T2',
                'humidity': 'HR2', 
                'precipitation': 'PP',
                'wind_speed': 'magViento10',
                'wind_direction': 'dirViento10',
                'pressure': 'PSFC'
            }
            
            # Extraer todos los datos vectorizadamente
            extracted_data = {}
            for var_name, dataset_var in variables_map.items():
                if dataset_var in dataset:
                    # Extrae todos los puntos de una vez usando indexación avanzada
                    # Necesitamos usar xr.DataArray.isel con arrays de índices para obtener valores escalares
                    var_data = dataset[dataset_var].isel(time=0).values[y_grids, x_grids]
                    extracted_data[var_name] = var_data
                else:
                    logger.warning(f"Variable {dataset_var} no encontrada en dataset")
                    extracted_data[var_name] = [None] * len(coordinates)
            
            # Soil moisture (opcional)
            if 'SMOIS' in dataset:
                soil_data = dataset['SMOIS'].isel(time=0).values[y_grids, x_grids]
                extracted_data['soil_moisture'] = soil_data
            else:
                extracted_data['soil_moisture'] = [None] * len(coordinates)
            
            # 3. Construir lista de resultados de manera eficiente
            results = []
            for i in range(len(coordinates)):
                try:
                    # Verificar si los datos están disponibles y convertir a escalar
                    def safe_extract(data_array, index):
                        """Extrae de manera segura un valor escalar de un array numpy"""
                        if data_array is None or len(data_array) <= index:
                            return None
                        try:
                            value = data_array[index]
                            # Convertir numpy scalar a Python float
                            return float(value.item() if hasattr(value, 'item') else value)
                        except (ValueError, TypeError, AttributeError):
                            return None
                    
                    result = {
                        "temperature": safe_extract(extracted_data['temperature'], i),
                        "humidity": safe_extract(extracted_data['humidity'], i),
                        "precipitation": safe_extract(extracted_data['precipitation'], i),
                        "wind_speed": safe_extract(extracted_data['wind_speed'], i),
                        "wind_direction": safe_extract(extracted_data['wind_direction'], i),
                        "pressure": safe_extract(extracted_data['pressure'], i),
                        "soil_moisture": safe_extract(extracted_data['soil_moisture'], i)
                    }
                    
                    results.append(result)
                    
                except Exception as e:
                    logger.error(f"Error procesando coordenada {i+1} ({coordinates[i][0]}, {coordinates[i][1]}): {e}")
                    results.append(None)
            
            successful = len([r for r in results if r is not None])
            logger.info(f"✅ Batch vectorizado procesado: {successful}/{len(coordinates)} coordenadas exitosas")
            
            return results
            
        except Exception as e:
            logger.error(f"Error en procesamiento vectorizado: {e}")
            # Fallback al método original si falla la vectorización
            logger.info("🔄 Fallback a procesamiento secuencial...")
            return self._process_dataset_batch_fallback(dataset, coordinates)
    
    def _process_dataset_batch_fallback(self, dataset: xr.Dataset, coordinates: List[Tuple[float, float]]) -> List[Optional[Dict]]:
        """
        Método fallback con bucle tradicional si la vectorización falla.
        """
        results = []
        
        for i, (latitude, longitude) in enumerate(coordinates):
            try:
                y_grid, x_grid = self._lat_lon_to_grid_coords(latitude, longitude, dataset)
                
                result = {
                    "temperature": float(dataset.T2.isel(time=0, y=y_grid, x=x_grid).values),
                    "humidity": float(dataset.HR2.isel(time=0, y=y_grid, x=x_grid).values),
                    "precipitation": float(dataset.PP.isel(time=0, y=y_grid, x=x_grid).values),
                    "wind_speed": float(dataset.magViento10.isel(time=0, y=y_grid, x=x_grid).values),
                    "wind_direction": float(dataset.dirViento10.isel(time=0, y=y_grid, x=x_grid).values),
                    "pressure": float(dataset.PSFC.isel(time=0, y=y_grid, x=x_grid).values),
                    "soil_moisture": float(dataset.SMOIS.isel(time=0, y=y_grid, x=x_grid).values) if 'SMOIS' in dataset else None
                }
                
                results.append(result)
                
            except Exception as e:
                logger.error(f"Error procesando coordenada {i+1} ({latitude}, {longitude}): {e}")
                results.append(None)
        
        successful = len([r for r in results if r is not None])
        logger.info(f"✅ Batch fallback procesado: {successful}/{len(coordinates)} coordenadas exitosas")
        
        return results
    
    def clear_cache(self):
        """Limpia el cache del dataset para forzar nueva descarga."""
        self._cached_dataset = None
        self._cached_path = None
        logger.debug("🗑️  Cache de dataset limpiado") 