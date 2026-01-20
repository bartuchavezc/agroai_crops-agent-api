# src/ingestion/reception/adapters/smn_adapter.py
"""
SMN (Servicio Meteorologico Nacional - Argentina) data adapter.
Fetches weather forecast data from SMN's public S3 bucket.
"""
import s3fs
import xarray as xr
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


class SMNAdapter:
    """
    Adapter for fetching weather data from SMN Argentina.
    
    Uses SMN's public WRF model data stored in S3.
    Data is available in NetCDF format with two daily cycles (00 UTC and 12 UTC).
    """
    
    def __init__(self):
        self.s3_client = s3fs.S3FileSystem(anon=True)
        self.base_path = "smn-ar-wrf"
        self._cached_dataset = None
        self._cached_path = None
    
    def _get_smn_forecast_cycle(self, current_time: datetime) -> tuple[datetime, int]:
        """
        Determine which SMN forecast cycle to use.
        
        SMN official: Only 2 cycles per day (00 UTC and 12 UTC)
        Logic: UTC >= 12 → use 12 UTC, else → use 00 UTC
        """
        # Argentina UTC-3: add 3 hours
        utc_time = current_time + timedelta(hours=3)
        utc_hour = utc_time.hour
        
        if utc_hour >= 12:
            smn_hour = 12
            target_date = current_time
        elif utc_hour >= 6:
            smn_hour = 0
            target_date = current_time
        else:
            smn_hour = 0
            target_date = current_time - timedelta(days=1)
        
        logger.info(f"Time {current_time.hour:02d}:00 ARG → {utc_hour:02d}:00 UTC → using SMN cycle {smn_hour:02d} UTC")
        
        return target_date.replace(minute=0, second=0, microsecond=0), smn_hour
    
    def _build_path(self, cycle_date: datetime, target_hour: int, frequency: str = "01H") -> str:
        """Build S3 path for SMN data file."""
        return (
            f"{self.base_path}/DATA/WRF/DET/"
            f"{cycle_date.year:04d}/{cycle_date.month:02d}/{cycle_date.day:02d}/"
            f"{target_hour:02d}/WRFDETAR_{frequency}_{cycle_date.strftime('%Y%m%d')}_"
            f"{target_hour:02d}_000.nc"
        )
    
    def _lat_lon_to_grid_coords(self, lat: float, lon: float, dataset: xr.Dataset) -> tuple[int, int]:
        """
        Convert geographic coordinates (lat, lon) to SMN grid coordinates (y, x).
        
        SMN WRF files use Lambert Conformal Conic projection over Argentina.
        Approximate bounds:
        - Latitude: -55° to -21° (South to North)
        - Longitude: -73° to -53° (West to East)
        """
        try:
            lat_min, lat_max = -55.0, -21.0
            lon_min, lon_max = -73.0, -53.0
            
            ny = dataset.sizes['y']
            nx = dataset.sizes['x']
            
            lat_clipped = np.clip(lat, lat_min, lat_max)
            lon_clipped = np.clip(lon, lon_min, lon_max)
            
            y_grid = int((lat_clipped - lat_min) / (lat_max - lat_min) * (ny - 1))
            x_grid = int((lon_clipped - lon_min) / (lon_max - lon_min) * (nx - 1))
            
            y_grid = np.clip(y_grid, 0, ny - 1)
            x_grid = np.clip(x_grid, 0, nx - 1)
            
            logger.debug(f"Geographic ({lat:.4f}, {lon:.4f}) → Grid ({y_grid}, {x_grid})")
            return y_grid, x_grid
            
        except Exception as e:
            logger.error(f"Error converting coordinates: {e}")
            y_center = dataset.sizes['y'] // 2
            x_center = dataset.sizes['x'] // 2
            logger.warning(f"Using center as fallback: ({y_center}, {x_center})")
            return y_center, x_center
    
    async def get_forecast(
        self,
        date: datetime,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        frequency: str = "01H"
    ) -> Optional[Dict]:
        """
        Get weather forecast from SMN for specific coordinates.
        
        Args:
            date: Target date
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            frequency: Data frequency (default "01H")
            
        Returns:
            Dictionary with weather data or None if fetch fails
        """
        try:
            cycle_date, smn_hour = self._get_smn_forecast_cycle(date)
            path = self._build_path(cycle_date, smn_hour, frequency)
            logger.info(f"Fetching SMN data from: {path}")
            
            try:
                with self.s3_client.open(path) as f:
                    dataset = xr.open_dataset(f)
                    result = self._process_dataset(dataset, latitude, longitude)
                    logger.info(f"SMN data fetched successfully for cycle {smn_hour:02d} UTC")
                    return result
            except Exception as e:
                logger.error(f"Error for cycle {smn_hour:02d} UTC: {type(e).__name__}: {e}")
                
                # Fallback to other official cycle
                fallback_hour = 0 if smn_hour == 12 else 12
                fallback_date = cycle_date if smn_hour == 12 else cycle_date - timedelta(days=1)
                fallback_path = self._build_path(fallback_date, fallback_hour, frequency)
                
                logger.info(f"Trying fallback: {fallback_path}")
                
                try:
                    with self.s3_client.open(fallback_path) as f:
                        dataset = xr.open_dataset(f)
                        result = self._process_dataset(dataset, latitude, longitude)
                        logger.info(f"SMN data fetched with fallback cycle {fallback_hour:02d} UTC")
                        return result
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed: {type(fallback_error).__name__}: {fallback_error}")
                    
        except Exception as e:
            logger.error(f"Error getting SMN data: {e}")
            return None
    
    def _process_dataset(
        self,
        dataset: xr.Dataset,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None
    ) -> Dict:
        """Process xarray dataset extracting data for the requested point."""
        try:
            if latitude is not None and longitude is not None:
                y_grid, x_grid = self._lat_lon_to_grid_coords(latitude, longitude, dataset)
            else:
                y_grid = dataset.sizes['y'] // 2
                x_grid = dataset.sizes['x'] // 2
            
            result = {
                "temperature": float(dataset.T2.isel(time=0, y=y_grid, x=x_grid).values),
                "humidity": float(dataset.HR2.isel(time=0, y=y_grid, x=x_grid).values),
                "precipitation": float(dataset.PP.isel(time=0, y=y_grid, x=x_grid).values),
                "wind_speed": float(dataset.magViento10.isel(time=0, y=y_grid, x=x_grid).values),
                "wind_direction": float(dataset.dirViento10.isel(time=0, y=y_grid, x=x_grid).values),
                "pressure": float(dataset.PSFC.isel(time=0, y=y_grid, x=x_grid).values),
                "soil_moisture": float(dataset.SMOIS.isel(time=0, y=y_grid, x=x_grid).values) if 'SMOIS' in dataset else None
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing dataset: {type(e).__name__}: {e}")
            raise
    
    async def get_forecast_batch(
        self,
        coordinates: List[Tuple[float, float]],
        date: datetime,
        frequency: str = "01H"
    ) -> List[Optional[Dict]]:
        """
        Get forecast for multiple coordinates using the same dataset.
        Optimized to reduce repeated NetCDF downloads.
        
        Args:
            coordinates: List of (latitude, longitude) tuples
            date: Target date
            frequency: Data frequency
            
        Returns:
            List of weather data dictionaries (or None if fetch fails)
        """
        try:
            cycle_date, smn_hour = self._get_smn_forecast_cycle(date)
            path = self._build_path(cycle_date, smn_hour, frequency)
            
            logger.info(f"Batch fetch for {len(coordinates)} coordinates from: {path}")
            
            dataset = await self._get_dataset_cached(path)
            if dataset is not None:
                return self._process_dataset_batch(dataset, coordinates)
            
            # Fallback
            fallback_hour = 0 if smn_hour == 12 else 12
            fallback_date = cycle_date if smn_hour == 12 else cycle_date - timedelta(days=1)
            fallback_path = self._build_path(fallback_date, fallback_hour, frequency)
            
            logger.info(f"Trying fallback batch: {fallback_path}")
            dataset = await self._get_dataset_cached(fallback_path)
            if dataset is not None:
                return self._process_dataset_batch(dataset, coordinates)
            
            logger.error("Fallback batch also failed")
            return [None] * len(coordinates)
            
        except Exception as e:
            logger.error(f"Error in batch fetch: {e}")
            return [None] * len(coordinates)
    
    async def _get_dataset_cached(self, path: str) -> Optional[xr.Dataset]:
        """Get dataset with simple caching to avoid repeated downloads."""
        try:
            if self._cached_path == path and self._cached_dataset is not None:
                logger.debug(f"Using cached dataset: {path}")
                return self._cached_dataset
            
            logger.debug(f"Downloading new dataset: {path}")
            with self.s3_client.open(path) as f:
                dataset = xr.open_dataset(f)
                dataset = dataset.load()  # Load into memory
                
                self._cached_dataset = dataset
                self._cached_path = path
                
                return dataset
                
        except Exception as e:
            logger.error(f"Error getting dataset {path}: {type(e).__name__}: {e}")
            return None
    
    def _process_dataset_batch(
        self,
        dataset: xr.Dataset,
        coordinates: List[Tuple[float, float]]
    ) -> List[Optional[Dict]]:
        """Process multiple coordinates from the same dataset using vectorized operations."""
        if not coordinates:
            return []
        
        try:
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
            
            extracted_data = {}
            for var_name, dataset_var in variables_map.items():
                if dataset_var in dataset:
                    var_data = dataset[dataset_var].isel(time=0).values[y_grids, x_grids]
                    extracted_data[var_name] = var_data
                else:
                    extracted_data[var_name] = [None] * len(coordinates)
            
            if 'SMOIS' in dataset:
                extracted_data['soil_moisture'] = dataset['SMOIS'].isel(time=0).values[y_grids, x_grids]
            else:
                extracted_data['soil_moisture'] = [None] * len(coordinates)
            
            results = []
            for i in range(len(coordinates)):
                try:
                    def safe_extract(data_array, index):
                        if data_array is None or len(data_array) <= index:
                            return None
                        try:
                            value = data_array[index]
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
                    logger.error(f"Error processing coordinate {i+1}: {e}")
                    results.append(None)
            
            successful = len([r for r in results if r is not None])
            logger.info(f"Batch processed: {successful}/{len(coordinates)} coordinates successful")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in vectorized processing: {e}")
            return [None] * len(coordinates)
    
    def clear_cache(self):
        """Clear dataset cache to force new download."""
        self._cached_dataset = None
        self._cached_path = None
        logger.debug("Dataset cache cleared")
