"""
SMN (Servicio Meteorológico Nacional, Argentina) forecast ETL.

Source: public bucket s3://smn-ar-wrf (WRF-ARW deterministic run, 4 km grid, Lambert projection).
    DATA/WRF/DET/YYYY/MM/DD/HH/WRFDETAR_01H_YYYYMMDD_HH_LLL.nc   hourly, LLL = lead hour 000..072
    DATA/WRF/DET/YYYY/MM/DD/HH/WRFDETAR_24H_YYYYMMDD_HH_DDD.nc   daily Tmin/Tmax, DDD = day 000..003
Each file carries 2-D `lat`/`lon` coordinate arrays and one time step per variable.

Pipeline (run as a batch):
    1. extract  - find the latest complete cycle and download the files we need
    2. match    - map each requested point (our fields) to the nearest grid cell (grid cached on disk)
    3. transform- read T2 / HR2 / PP / wind at those cells (+ daily Tmin / Tmax)
    4. load     - upsert into the `weather_forecasts` hypertable (newer cycles overwrite older values)

The ETL receives the points to process; it does not know what a field is.
"""
import asyncio
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import s3fs
import xarray as xr
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import WeatherForecast, round_coord

logger = logging.getLogger(__name__)

BUCKET_ROOT = "smn-ar-wrf/DATA/WRF/DET"
SOURCE = "smn_wrf"
HOURLY_VARS = {"temperature": "T2", "humidity": "HR2", "precipitation_accum": "PP", "wind_speed": "magViento10"}
DAILY_VARS = {"tmin": "Tmin", "tmax": "Tmax"}
MAX_MATCH_DISTANCE_DEG = 0.1
DOWNLOAD_WORKERS = 4


@dataclass(frozen=True)
class Cycle:
    run: datetime  # model initialization time, UTC
    hourly_files: tuple[str, ...]
    daily_files: tuple[str, ...]

    @property
    def label(self) -> str:
        return self.run.strftime("%Y-%m-%d %HZ")


@dataclass
class ETLResult:
    status: str
    cycle: Optional[str] = None
    points_requested: int = 0
    points_matched: int = 0
    rows_loaded: int = 0
    unmatched_points: list[tuple[float, float]] = field(default_factory=list)


class SMNForecastETL:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache_dir: str,
        horizon_hours: int = 72,
        hourly_step: int = 3,
        filesystem: Optional[s3fs.S3FileSystem] = None,
    ):
        self.session_factory = session_factory
        self.cache_dir = Path(cache_dir)
        self.horizon_hours = horizon_hours
        self.hourly_step = max(1, hourly_step)
        self.fs = filesystem or s3fs.S3FileSystem(anon=True)

    # ------------------------------------------------------------------ batch entrypoint

    async def run(self, points: Iterable[tuple[float, float]], force: bool = False) -> ETLResult:
        unique_points = sorted({(round_coord(lat), round_coord(lon)) for lat, lon in points})
        if not unique_points:
            return ETLResult(status="skipped_no_points")

        cycle = await asyncio.to_thread(self.latest_complete_cycle)
        if cycle is None:
            return ETLResult(status="no_complete_cycle", points_requested=len(unique_points))

        # Points outside the model domain can never be loaded; don't let them force a re-run.
        grid = self._cached_grid()
        check_points = list(self.match_points(unique_points, *grid)[0]) if grid else unique_points
        if not check_points:
            return ETLResult(status="no_points_in_domain", cycle=cycle.label, points_requested=len(unique_points))
        if not force and check_points and await self._already_loaded(cycle, check_points):
            return ETLResult(status="up_to_date", cycle=cycle.label, points_requested=len(unique_points))

        rows, matched, unmatched = await asyncio.to_thread(self._extract_transform, cycle, unique_points)
        loaded = await self._load(rows)
        logger.info(f"SMN ETL {cycle.label}: {matched}/{len(unique_points)} points, {loaded} rows")
        return ETLResult(
            status="loaded",
            cycle=cycle.label,
            points_requested=len(unique_points),
            points_matched=matched,
            rows_loaded=loaded,
            unmatched_points=unmatched,
        )

    # ------------------------------------------------------------------ extract

    def latest_complete_cycle(self, now: Optional[datetime] = None) -> Optional[Cycle]:
        """Newest run (checking the last 3 days) that already has every file we need."""
        now = now or datetime.now(timezone.utc)
        needed_leads = set(range(0, self.horizon_hours + 1, self.hourly_step))
        for days_back in range(3):
            day = now - timedelta(days=days_back)
            day_dir = f"{BUCKET_ROOT}/{day:%Y/%m/%d}"
            try:
                runs = sorted(self.fs.ls(day_dir), reverse=True)
            except FileNotFoundError:
                continue
            for run_dir in runs:
                hour = run_dir.rstrip("/").rsplit("/", 1)[-1]
                if not hour.isdigit():
                    continue
                files = self.fs.ls(run_dir)
                hourly = {int(Path(f).stem.rsplit("_", 1)[-1]): f for f in files if "_01H_" in f}
                daily = sorted(f for f in files if "_24H_" in f)
                if needed_leads.issubset(hourly) and daily:
                    run = datetime(day.year, day.month, day.day, int(hour), tzinfo=timezone.utc)
                    return Cycle(
                        run=run,
                        hourly_files=tuple(hourly[lead] for lead in sorted(needed_leads)),
                        daily_files=tuple(daily),
                    )
        return None

    def _download_all(self, paths: list[str], workdir: Path) -> dict[str, Path]:
        def fetch(path: str) -> tuple[str, Path]:
            local = workdir / Path(path).name
            self.fs.get(path, str(local))
            return path, local

        with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
            return dict(pool.map(fetch, paths))

    # ------------------------------------------------------------------ match

    @property
    def _grid_cache(self) -> Path:
        return self.cache_dir / "smn_wrf_grid.npz"

    def _cached_grid(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        if not self._grid_cache.exists():
            return None
        data = np.load(self._grid_cache)
        return data["lat"], data["lon"]

    def _grid(self, sample_file: Path) -> tuple[np.ndarray, np.ndarray]:
        """lat/lon arrays are identical for every file of the model; cache them on disk."""
        cached = self._cached_grid()
        if cached:
            return cached
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache = self._grid_cache
        with xr.open_dataset(sample_file, engine="h5netcdf") as ds:
            lat, lon = ds["lat"].values.astype(np.float32), ds["lon"].values.astype(np.float32)
        np.savez_compressed(cache, lat=lat, lon=lon)
        return lat, lon

    @staticmethod
    def match_points(
        points: list[tuple[float, float]], lat: np.ndarray, lon: np.ndarray
    ) -> tuple[dict[tuple[float, float], tuple[int, int]], list[tuple[float, float]]]:
        """Nearest grid cell per point; points outside the model domain are returned as unmatched."""
        matched: dict[tuple[float, float], tuple[int, int]] = {}
        unmatched: list[tuple[float, float]] = []
        for p_lat, p_lon in points:
            dlat = lat - p_lat
            dlon = (lon - p_lon) * np.cos(np.radians(p_lat))
            dist2 = dlat * dlat + dlon * dlon
            flat = int(np.argmin(dist2))
            if dist2.flat[flat] > MAX_MATCH_DISTANCE_DEG**2:
                unmatched.append((p_lat, p_lon))
                continue
            matched[(p_lat, p_lon)] = tuple(int(i) for i in np.unravel_index(flat, lat.shape))
        return matched, unmatched

    # ------------------------------------------------------------------ transform

    @staticmethod
    def _read_values(path: Path, variables: dict[str, str], cells: list[tuple[int, int]]):
        ys = xr.DataArray([c[0] for c in cells], dims="point")
        xs = xr.DataArray([c[1] for c in cells], dims="point")
        with xr.open_dataset(path, engine="h5netcdf") as ds:
            valid_time = ds["time"].values[0].astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc)
            values = {}
            for column, var in variables.items():
                if var in ds:
                    arr = ds[var].isel(time=0).isel(y=ys, x=xs).values
                    values[column] = [None if np.isnan(v) else float(v) for v in arr]
                else:
                    values[column] = [None] * len(cells)
        return valid_time, values

    def _extract_transform(self, cycle: Cycle, points: list[tuple[float, float]]):
        with tempfile.TemporaryDirectory(prefix="smn_") as tmp:
            local = self._download_all(list(cycle.hourly_files + cycle.daily_files), Path(tmp))
            lat, lon = self._grid(local[cycle.hourly_files[0]])
            matched, unmatched = self.match_points(points, lat, lon)
            if not matched:
                return [], 0, unmatched

            keys = list(matched)
            cells = [matched[k] for k in keys]
            rows: list[dict] = []
            for resolution, files, variables in (
                ("1h", cycle.hourly_files, HOURLY_VARS),
                ("24h", cycle.daily_files, DAILY_VARS),
            ):
                for remote in files:
                    valid_time, values = self._read_values(local[remote], variables, cells)
                    for i, (p_lat, p_lon) in enumerate(keys):
                        row = {
                            "time": valid_time,
                            "latitude": p_lat,
                            "longitude": p_lon,
                            "source": SOURCE,
                            "resolution": resolution,
                            "issued_at": cycle.run,
                        }
                        row.update({column: None for column in (*HOURLY_VARS, *DAILY_VARS)})
                        row.update({column: values[column][i] for column in variables})
                        rows.append(row)
        return rows, len(matched), unmatched

    # ------------------------------------------------------------------ load

    async def _already_loaded(self, cycle: Cycle, points: list[tuple[float, float]]) -> bool:
        async with self.session_factory() as session:
            loaded = (
                await session.execute(
                    select(WeatherForecast.latitude, WeatherForecast.longitude)
                    .where(WeatherForecast.source == SOURCE, WeatherForecast.issued_at == cycle.run)
                    .distinct()
                )
            ).all()
        return set(points).issubset({(row[0], row[1]) for row in loaded})

    async def _load(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        table = WeatherForecast.__table__
        update_cols = ["issued_at", *HOURLY_VARS, *DAILY_VARS]
        async with self.session_factory() as session:
            for start in range(0, len(rows), 1000):
                stmt = insert(table).values(rows[start:start + 1000])
                stmt = stmt.on_conflict_do_update(
                    index_elements=["time", "latitude", "longitude", "source", "resolution"],
                    set_={c: stmt.excluded[c] for c in update_cols},
                    where=table.c.issued_at <= stmt.excluded.issued_at,
                )
                await session.execute(stmt)
            await session.commit()
        return len(rows)
