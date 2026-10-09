"""
CopernicusAdapter parsing, against the shapes the real Statistical API returns: a cloud-masked/no-data
interval reports its stats as the JSON string "NaN" (JSON has no native NaN) rather than omitting the key —
this once crashed the DB insert with "invalid input for query argument: 'NaN'".
"""
import math
from datetime import date

from src.providers.satellite.copernicus import CopernicusAdapter, _processing_units

_NAN = {"min": "NaN", "max": "NaN", "mean": "NaN", "stDev": "NaN", "sampleCount": 100, "noDataCount": 100}


def _band(mean, samples=100, no_data=0, geometry=None, percentiles=None):
    stats = {"min": mean - 0.1, "max": mean + 0.1, "mean": mean, "stDev": 0.05,
             "sampleCount": samples, "noDataCount": no_data}
    if geometry is not None:
        stats["geometryPixelCount"] = geometry
    if percentiles is not None:
        stats["percentiles"] = percentiles
    return {"stats": stats}


def _s2_interval(day, ndvi=0.6, **pixels):
    bands = {
        "B0": _band(ndvi, percentiles={"10.0": ndvi - 0.1, "50.0": ndvi, "90.0": ndvi + 0.1}, **pixels),
        "B1": _band(0.3, **pixels),
        "B2": _band(0.2, **pixels),
        "B3": _band(0.5, **pixels),
        "B4": _band(-0.4, **pixels),
    }
    interval = {"from": f"{day}T00:00:00Z", "to": f"{day}T23:59:59Z"}
    return {"interval": interval, "outputs": {"indices": {"bands": bands}}}


def _nan_s2_interval(day):
    bands = {f"B{i}": {"stats": dict(_NAN)} for i in range(5)}
    return {"interval": {"from": f"{day}T00:00:00Z"}, "outputs": {"indices": {"bands": bands}}}


def test_s2_parses_every_index_and_percentiles():
    [obs] = CopernicusAdapter._parse_s2({"data": [_s2_interval("2026-01-05", ndvi=0.62)]})
    assert obs.observed_on == date(2026, 1, 5)
    assert obs.ndvi_mean == 0.62
    assert obs.ndvi_std == 0.05
    assert math.isclose(obs.ndvi_p10, 0.52) and obs.ndvi_p50 == 0.62 and math.isclose(obs.ndvi_p90, 0.72)
    assert (obs.ndre_mean, obs.ndmi_mean, obs.evi_mean, obs.ndwi_mean) == (0.3, 0.2, 0.5, -0.4)


def test_fully_masked_pass_is_dropped_not_stored_as_nan():
    payload = {"data": [_nan_s2_interval("2026-01-05"), _s2_interval("2026-01-10")]}
    observations = CopernicusAdapter._parse_s2(payload)
    assert [o.observed_on for o in observations] == [date(2026, 1, 10)]


def test_valid_fraction_uses_the_drawn_geometry_as_denominator():
    # 400 px in the bbox, 100 inside the polygon, 330 masked (300 outside + 30 clouded) -> 70/100 clear.
    [obs] = CopernicusAdapter._parse_s2({"data": [_s2_interval("2026-01-05", samples=400, no_data=330, geometry=100)]})
    assert obs.total_pixels == 100
    assert obs.valid_pixels == 70
    assert obs.valid_fraction == 0.7


def test_valid_fraction_falls_back_to_the_box_without_a_polygon():
    [obs] = CopernicusAdapter._parse_s2({"data": [_s2_interval("2026-01-05", samples=200, no_data=50)]})
    assert (obs.total_pixels, obs.valid_pixels, obs.valid_fraction) == (200, 150, 0.75)


def test_errored_and_empty_intervals_are_skipped():
    payload = {"data": [{"interval": {"from": "2026-01-01T00:00:00Z"}, "error": {"type": "EXECUTION_ERROR"}}]}
    assert CopernicusAdapter._parse_s2(payload) == []
    assert CopernicusAdapter._parse_s2({}) == []


def test_s1_converts_linear_means_to_db_and_cross_ratio():
    bands = {"B0": _band(0.1), "B1": _band(0.01), "B2": _band(0.36)}
    payload = {"data": [{"interval": {"from": "2026-02-01T00:00:00Z"}, "outputs": {"backscatter": {"bands": bands}}}]}
    [obs] = CopernicusAdapter._parse_s1(payload, "DESCENDING")
    assert obs.vv_db_mean == -10.0
    assert obs.vh_db_mean == -20.0
    assert obs.vh_vv_db == -10.0
    assert obs.rvi_mean == 0.36
    assert obs.orbit_direction == "DESCENDING"


def test_year_chunks_cover_the_range_without_gaps_or_overlap():
    chunks = CopernicusAdapter._year_chunks(date(2023, 1, 1), date(2025, 6, 30))
    assert chunks[0][0] == date(2023, 1, 1) and chunks[-1][1] == date(2025, 6, 30)
    for (_, end), (start, _) in zip(chunks, chunks[1:], strict=False):
        assert (start - end).days == 1
    assert all((end - start).days <= 365 for start, end in chunks)


def test_geometry_hash_changes_with_the_boundary():
    polygon = [(-34.60, -58.40), (-34.61, -58.40), (-34.61, -58.41)]
    box = CopernicusAdapter.geometry_hash(-34.6, -58.4)
    drawn = CopernicusAdapter.geometry_hash(-34.6, -58.4, polygon)
    assert box != drawn
    assert drawn == CopernicusAdapter.geometry_hash(-34.6, -58.4, list(polygon))


def test_processing_units_header():
    assert _processing_units({"x-processingunits-spent": "0.0123"}) == 0.0123
    assert _processing_units({}) is None
    assert _processing_units({"x-processingunits-spent": "n/a"}) is None


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


def _quality_interval(day, cloud, shadow, unusable, samples=100, no_data=0, geometry=None):
    def band(mean):
        stats = {"mean": mean, "min": 0, "max": 1, "stDev": 0.1, "sampleCount": samples, "noDataCount": no_data}
        if geometry is not None:
            stats["geometryPixelCount"] = geometry
        return {"stats": stats}

    bands = {"B0": band(cloud), "B1": band(shadow), "B2": band(unusable)}
    return {"interval": {"from": f"{day}T00:00:00Z"}, "outputs": {"scl": {"bands": bands}}}


def test_quality_parses_the_share_of_each_cause_per_date():
    payload = {"data": [
        _quality_interval("2026-01-05", 0.62, 0.1, 0.0),
        _quality_interval("2026-01-10", 0.0, 0.0, 0.0),
        _quality_interval("2026-01-15", 1.2, -0.1, "NaN"),  # out-of-range values are clamped, NaN is unknown
        _quality_interval("2026-01-20", 0.5, 0.5, 0.0, samples=100, no_data=100),  # no scene data: dropped
        {"interval": {"from": "2026-01-25T00:00:00Z"}, "error": {"message": "boom"}, "outputs": {}},
    ]}
    rows = CopernicusAdapter._parse_quality(payload)
    assert [(q.observed_on.day, q.cloud_fraction, q.shadow_fraction, q.nodata_fraction) for q in rows] == [
        (5, 0.62, 0.1, 0.0), (10, 0.0, 0.0, 0.0), (15, 1.0, 0.0, None),
    ]
    assert rows[0].total_pixels == 100
