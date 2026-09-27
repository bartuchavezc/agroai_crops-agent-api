from datetime import datetime, timezone

import numpy as np

from src.providers.weather.smn import SMNForecastETL


def _grid():
    lats = np.linspace(-55, -21, 69, dtype=np.float32)
    lons = np.linspace(-73, -53, 41, dtype=np.float32)
    lon, lat = np.meshgrid(lons, lats)
    return lat, lon


def test_match_points_nearest_cell_and_out_of_domain():
    lat, lon = _grid()
    matched, unmatched = SMNForecastETL.match_points([(-34.5, -58.5), (40.4, -3.7)], lat, lon)
    iy, ix = matched[(-34.5, -58.5)]
    assert abs(lat[iy, ix] - -34.5) <= 0.25 and abs(lon[iy, ix] - -58.5) <= 0.25
    assert unmatched == [(40.4, -3.7)]


class FakeFS:
    def __init__(self, tree):
        self.tree = tree

    def ls(self, path):
        if path not in self.tree:
            raise FileNotFoundError(path)
        return self.tree[path]


def test_latest_complete_cycle_skips_incomplete_runs(tmp_path):
    root = "smn-ar-wrf/DATA/WRF/DET/2026/09/26"
    complete = f"{root}/06"
    incomplete = f"{root}/12"
    tree = {
        root: [complete, incomplete],
        complete: [f"{complete}/WRFDETAR_01H_20260926_06_{h:03d}.nc" for h in range(0, 73)]
        + [f"{complete}/WRFDETAR_24H_20260926_06_{d:03d}.nc" for d in range(4)],
        incomplete: [f"{incomplete}/WRFDETAR_01H_20260926_12_{h:03d}.nc" for h in range(0, 10)],
    }
    etl = SMNForecastETL(session_factory=None, cache_dir=str(tmp_path), hourly_step=3, filesystem=FakeFS(tree))
    cycle = etl.latest_complete_cycle(now=datetime(2026, 9, 26, 20, tzinfo=timezone.utc))
    assert cycle.run == datetime(2026, 9, 26, 6, tzinfo=timezone.utc)
    assert len(cycle.hourly_files) == 25 and cycle.hourly_files[-1].endswith("_072.nc")
    assert len(cycle.daily_files) == 4
