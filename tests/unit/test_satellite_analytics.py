"""Satellite series analytics (application/satellite/analytics.py) on synthetic seasons: a known curve
plus noise, cloud dips and gaps, so each derived number can be checked against the truth."""
import math
import random
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from src.application.alerts.rules_engine import RulesEngine
from src.application.satellite import analytics
from src.application.satellite.service import rule_context, summarize

TODAY = date(2026, 2, 20)


def _curve(day: date, amplitude: float = 0.6, peak_doy: int = 40) -> float:
    """Summer crop: base 0.2, Gaussian bump peaking around Feb 9 (southern hemisphere)."""
    doy = day.timetuple().tm_yday
    distance = ((doy - peak_doy + 182) % 365) - 182
    return 0.2 + amplitude * math.exp(-(distance ** 2) / (2 * 35 ** 2))


def _obs(day: date, ndvi: float, valid_fraction: float = 1.0, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        observed_on=day, ndvi_mean=ndvi, ndre_mean=ndvi * 0.6, ndmi_mean=extra.get("ndmi", ndvi * 0.3),
        evi_mean=ndvi * 0.8, ndwi_mean=-ndvi * 0.7, valid_fraction=valid_fraction, valid_pixels=500,
        ndvi_std=0.05, ndvi_p10=ndvi - 0.1, ndvi_p90=ndvi + 0.1,
    )


def _series(start: date, end: date, amplitude_for=lambda d: 0.6, noise: float = 0.015, seed: int = 7) -> list:
    rng = random.Random(seed)
    out, day = [], start
    while day <= end:
        out.append(_obs(day, _curve(day, amplitude_for(day)) + rng.gauss(0, noise)))
        day += timedelta(days=5)
    return out


def test_clean_drops_cloudy_passes_and_isolated_dips():
    days = [date(2026, 1, 1) + timedelta(days=5 * i) for i in range(5)]
    obs = [_obs(days[0], 0.6), _obs(days[1], 0.61), _obs(days[2], 0.3), _obs(days[3], 0.62),
           _obs(days[4], 0.63, valid_fraction=0.3)]
    kept = analytics.clean_s2(obs, min_valid_fraction=0.6)
    assert [o.observed_on for o in kept] == [days[0], days[1], days[3]]


def test_whittaker_recovers_the_underlying_curve():
    obs = _series(date(2025, 6, 1), TODAY)
    series = analytics.smooth(obs, "ndvi")
    errors = [abs(series.at(o.observed_on) - _curve(o.observed_on)) for o in obs]
    assert np.mean(errors) < 0.02


def test_upper_envelope_resists_residual_clouds():
    obs = _series(date(2025, 6, 1), TODAY)
    for o in obs[::7]:
        o.ndvi_mean -= 0.08  # haze that the scene classification and the dip filter both let through
    series = analytics.smooth(obs, "ndvi")
    bias = np.mean([series.at(o.observed_on) - _curve(o.observed_on) for o in obs])
    assert bias > -0.015


def test_banded_solver_matches_dense_solution():
    rng = np.random.default_rng(0)
    y = rng.normal(size=60)
    w = (rng.random(60) > 0.4).astype(float)
    lam = 50.0
    d = np.diff(np.eye(60), n=2, axis=0)
    dense = np.linalg.solve(np.diag(w) + lam * d.T @ d + 1e-9 * np.eye(60), w * y)
    assert np.allclose(analytics._whittaker(y, w, lam), dense, atol=1e-6)


def test_normal_and_anomaly_flag_a_season_worse_than_previous_years():
    obs = _series(date(2022, 6, 1), TODAY, amplitude_for=lambda d: 0.4 if d >= date(2025, 10, 1) else 0.6)
    result = analytics.analyze(obs, [], TODAY, min_valid_fraction=0.6)
    ndvi = result.metrics["ndvi"]
    assert ndvi["normal_years"] == 3
    assert ndvi["vs_normal"] < -0.1
    assert ndvi["position"] == "muy_por_debajo"
    assert ndvi["vs_last_year"] < -0.1
    assert ndvi["below_p10_streak"] >= 2


def test_no_normal_with_a_single_season_of_history():
    obs = _series(date(2025, 9, 1), TODAY)
    result = analytics.analyze(obs, [], TODAY)
    ndvi = result.metrics["ndvi"]
    assert ndvi["normal_years"] == 0
    assert ndvi["position"] is None
    assert any("Historia corta" in c for c in result.caveats)


def test_phenology_finds_green_up_peak_and_decline():
    end = date(2026, 4, 15)
    obs = _series(date(2025, 9, 1), end)
    pheno = analytics.phenology(analytics.smooth(obs, "ndvi"), date(2025, 10, 1), end, "ciclo_de_cultivo")
    assert pheno.stage in ("caida", "fin_de_ciclo")
    assert abs((pheno.peak_date - date(2026, 2, 9)).days) <= 10
    assert pheno.green_up_date < pheno.peak_date < pheno.decline_date


def test_phenology_reports_growth_while_still_rising():
    end = date(2026, 1, 15)
    obs = _series(date(2025, 9, 1), end)
    pheno = analytics.phenology(analytics.smooth(obs, "ndvi"), date(2025, 10, 1), end, "ciclo_de_cultivo")
    assert pheno.stage == "crecimiento"
    assert pheno.peak_provisional


def test_flat_series_has_no_marked_cycle():
    obs = [_obs(date(2025, 6, 1) + timedelta(days=5 * i), 0.7 + 0.01 * (i % 2)) for i in range(60)]
    pheno = analytics.phenology(analytics.smooth(obs, "ndvi"), date(2025, 6, 1), date(2026, 2, 1), "ventana_reciente")
    assert pheno.stage == "sin_ciclo_marcado"


def test_radar_trend_covers_an_optical_gap():
    s1 = [SimpleNamespace(observed_on=date(2026, 1, 1) + timedelta(days=6 * i), vh_vv_db=-8.0 + 0.4 * i, rvi_mean=0.5)
          for i in range(8)]
    signal = analytics.radar_signal(s1, last_s2=date(2026, 1, 5), today=date(2026, 2, 15))
    assert signal.gap_from == date(2026, 1, 5)
    assert signal.passes_in_gap == 7
    assert signal.trend == "sube"


def test_radar_has_no_gap_trend_when_optical_is_recent():
    s1 = [SimpleNamespace(observed_on=date(2026, 2, 10), vh_vv_db=-8.0, rvi_mean=0.5)]
    signal = analytics.radar_signal(s1, last_s2=date(2026, 2, 12), today=date(2026, 2, 15))
    assert signal.trend is None and signal.gap_from is None


def test_stale_optical_pass_is_flagged():
    obs = _series(date(2025, 9, 1), date(2026, 1, 20))
    result = analytics.analyze(obs, [], TODAY)
    assert result.days_since_last_pass >= 30
    assert any("hace" in c for c in result.caveats)


def test_weekly_table_is_bounded_and_has_normals_with_history():
    obs = _series(date(2022, 6, 1), TODAY)
    rows = analytics.weekly_table(obs, "ndvi", date(2023, 1, 1), TODAY, max_rows=60)
    assert len(rows) <= 60
    assert rows[-1]["normal_p50"] is not None
    assert all(set(r) >= {"week", "raw", "smoothed", "last_year"} for r in rows)


def test_no_data_analysis_is_explicit():
    result = analytics.analyze([], [], TODAY)
    assert not result.has_data
    assert result.caveats
    assert "Todavía no hay" in summarize(result)


@pytest.mark.parametrize("worse", [True, False])
def test_rule_context_feeds_the_rules_and_messages_render(worse):
    amplitude = (lambda d: 0.4 if d >= date(2025, 10, 1) else 0.6) if worse else (lambda d: 0.6)
    result = analytics.analyze(_series(date(2022, 6, 1), TODAY, amplitude_for=amplitude), [], TODAY)
    matches = RulesEngine().evaluate(rule_context(result), categories=["satellite"])
    ids = {m.rule_id for m in matches}
    if worse:
        assert {"satellite_below_normal", "satellite_worse_than_last_year"} <= ids
        assert all("{" not in m.message for m in matches)
    else:
        assert "satellite_below_normal" not in ids and "satellite_worse_than_last_year" not in ids
    assert result.to_dict()["last_pass"]["date"]  # JSON-friendly (dates as strings)


def _qobs(day, ndvi, valid=1.0, cloud=None, shadow=None, nodata=None):
    from types import SimpleNamespace

    return SimpleNamespace(
        observed_on=day, ndvi_mean=ndvi, ndmi_mean=0.2, valid_fraction=valid, cloud_fraction=cloud,
        shadow_fraction=shadow, nodata_fraction=nodata,
    )


def test_discard_reason_is_the_biggest_recorded_cause():
    assert analytics.discard_reason(_qobs(date(2026, 1, 1), None, 0.0, cloud=0.7, shadow=0.2, nodata=0.1)) == "clouds"
    assert analytics.discard_reason(_qobs(date(2026, 1, 1), None, 0.0, cloud=0.1, shadow=0.6, nodata=0.0)) == "shadow"
    assert analytics.discard_reason(_qobs(date(2026, 1, 1), None, 0.0, cloud=0.0, shadow=0.0, nodata=0.9)) == "nodata"
    assert analytics.discard_reason(_qobs(date(2026, 1, 1), None, 0.0)) == "unknown"  # stored before it was recorded
    assert analytics.discard_reason(_qobs(date(2026, 1, 1), None, 0.0, cloud=0.0, shadow=0.0, nodata=0.0)) == "unknown"


def test_pass_points_mark_what_the_analysis_ignored_and_why():
    d = date(2026, 3, 1)
    from datetime import timedelta

    passes = [
        _qobs(d, 0.60),
        _qobs(d + timedelta(days=5), 0.62),
        _qobs(d + timedelta(days=10), 0.30),  # an isolated dip between two good passes: residual cloud/haze
        _qobs(d + timedelta(days=15), 0.64),
        _qobs(d + timedelta(days=20), None, 0.0, cloud=0.1, shadow=0.8, nodata=0.0),  # fully masked, shadow
        _qobs(d + timedelta(days=25), 0.55, 0.3, cloud=0.65, shadow=0.0, nodata=0.05),  # too little clear surface
        _qobs(d + timedelta(days=30), 0.66),
    ]
    points = analytics.pass_points(passes, ["ndvi", "ndmi"], 0.6)
    assert [(p["date"][-5:], p["discarded"], p["discard_reason"]) for p in points] == [
        ("03-01", False, None), ("03-06", False, None), ("03-11", True, "clouds"), ("03-16", False, None),
        ("03-21", True, "shadow"), ("03-26", True, "clouds"), ("03-31", False, None),
    ]
    assert points[0]["ndvi_mean"] == 0.6 and points[0]["ndmi_mean"] == 0.2 and points[4]["ndvi_mean"] is None
