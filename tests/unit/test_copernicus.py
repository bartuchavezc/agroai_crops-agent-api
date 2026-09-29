"""
Regression tests for CopernicusAdapter._parse_stats: caught live against the real Copernicus Statistical
API, which reports a cloud-masked/no-data interval's stats as the JSON string "NaN" (not a JSON number,
since JSON has no native NaN) rather than omitting the key — this used to crash the DB insert with
"invalid input for query argument: 'NaN' (must be real number, not str)".
"""
from src.providers.satellite.copernicus import CopernicusAdapter


def _interval(ndvi_stats: dict, ndwi_stats: dict) -> dict:
    return {
        "outputs": {
            "ndvi": {"bands": {"B0": {"stats": ndvi_stats}}},
            "ndwi": {"bands": {"B0": {"stats": ndwi_stats}}},
        }
    }


_NAN_STATS = {"min": "NaN", "max": "NaN", "mean": "NaN", "stDev": "NaN", "sampleCount": 1, "noDataCount": 1}
_VALID_STATS = {"min": 0.25, "max": 0.25, "mean": 0.25, "stDev": 0.0, "sampleCount": 1, "noDataCount": 0}


def test_all_nan_interval_parses_to_none_not_the_string_nan():
    payload = {"data": [_interval(_NAN_STATS, _NAN_STATS)]}
    stats = CopernicusAdapter._parse_stats(payload)
    assert stats.ndvi_mean is None
    assert stats.ndvi_min is None
    assert stats.ndvi_max is None
    assert stats.ndwi_mean is None


def test_falls_back_to_an_earlier_valid_interval_when_the_latest_is_all_nan():
    payload = {
        "data": [
            _interval(_VALID_STATS, _VALID_STATS),  # older, valid
            _interval(_NAN_STATS, _NAN_STATS),  # most recent, cloud-masked
        ]
    }
    stats = CopernicusAdapter._parse_stats(payload)
    assert stats.ndvi_mean == 0.25
    assert stats.ndwi_mean == 0.25


def test_prefers_the_most_recent_valid_interval():
    payload = {
        "data": [
            _interval({**_VALID_STATS, "mean": 0.10}, {**_VALID_STATS, "mean": -0.10}),
            _interval({**_VALID_STATS, "mean": 0.40}, {**_VALID_STATS, "mean": -0.40}),
        ]
    }
    stats = CopernicusAdapter._parse_stats(payload)
    assert stats.ndvi_mean == 0.40
    assert stats.ndwi_mean == -0.40


def test_no_intervals_returns_none():
    assert CopernicusAdapter._parse_stats({"data": []}) is None
    assert CopernicusAdapter._parse_stats({}) is None


def test_pixel_count_is_geometry_pixels_minus_no_data():
    stats_with_geometry = {**_VALID_STATS, "geometryPixelCount": 12, "noDataCount": 2}
    payload = {"data": [_interval(stats_with_geometry, stats_with_geometry)]}
    stats = CopernicusAdapter._parse_stats(payload)
    assert stats.pixel_count == 10


def test_pixel_count_is_none_when_geometry_pixel_count_absent():
    payload = {"data": [_interval(_VALID_STATS, _VALID_STATS)]}
    stats = CopernicusAdapter._parse_stats(payload)
    assert stats.pixel_count is None


def test_bounds_falls_back_to_bbox_without_a_polygon():
    bounds = CopernicusAdapter._bounds(-34.6, -58.4)
    assert "bbox" in bounds
    assert "geometry" not in bounds


def test_bounds_builds_a_closed_geojson_polygon_from_lat_lon_pairs():
    polygon = [(-34.60, -58.40), (-34.61, -58.40), (-34.61, -58.41)]
    bounds = CopernicusAdapter._bounds(-34.6, -58.4, polygon)
    ring = bounds["geometry"]["coordinates"][0]
    assert bounds["geometry"]["type"] == "Polygon"
    # lon,lat order (GeoJSON), and the ring is closed (first point repeated as last).
    assert ring[0] == [-58.40, -34.60]
    assert ring[-1] == ring[0]
    assert len(ring) == len(polygon) + 1


def test_bounds_ignores_a_too_short_polygon():
    bounds = CopernicusAdapter._bounds(-34.6, -58.4, [(-34.60, -58.40), (-34.61, -58.40)])
    assert "bbox" in bounds
