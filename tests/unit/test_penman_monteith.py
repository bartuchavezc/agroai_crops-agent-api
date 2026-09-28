from src.application.irrigation.penman_monteith import Et0Inputs, build_et0_inputs, reference_et0_mm


def _inputs(**overrides) -> Et0Inputs:
    data = dict(
        latitude=-34.6,
        day_of_year=15,  # mid-January, Southern Hemisphere summer
        tmax_c=30.0,
        tmin_c=18.0,
        mean_humidity_pct=55.0,
        wind_speed_2m_ms=1.5,
        shortwave_radiation_mj_m2_day=22.0,
    )
    data.update(overrides)
    return Et0Inputs(**data)


def test_et0_is_positive_for_typical_summer_conditions():
    assert reference_et0_mm(_inputs()) > 0


def test_et0_increases_with_radiation():
    low = reference_et0_mm(_inputs(shortwave_radiation_mj_m2_day=10.0))
    high = reference_et0_mm(_inputs(shortwave_radiation_mj_m2_day=25.0))
    assert high > low


def test_et0_decreases_with_higher_humidity():
    dry = reference_et0_mm(_inputs(mean_humidity_pct=30.0))
    humid = reference_et0_mm(_inputs(mean_humidity_pct=90.0))
    assert humid < dry


def test_et0_increases_with_wind():
    calm = reference_et0_mm(_inputs(wind_speed_2m_ms=0.5))
    windy = reference_et0_mm(_inputs(wind_speed_2m_ms=6.0))
    assert windy > calm


def test_build_et0_inputs_returns_none_without_temperature():
    assert build_et0_inputs(-34.6, 15, None, 18.0, 55.0, 1.5, 22.0) is None
    assert build_et0_inputs(-34.6, 15, 30.0, None, 55.0, 1.5, 22.0) is None


def test_build_et0_inputs_falls_back_when_wind_and_humidity_missing():
    inputs = build_et0_inputs(-34.6, 15, 30.0, 18.0, None, None, 22.0)
    assert inputs is not None
    assert inputs.mean_humidity_pct == 60.0
    assert inputs.wind_speed_2m_ms > 0
