from src.providers.weather.summary import summarize_daily


def _day(i, tmax=24.0, tmin=10.0, rain=0.0, et0=4.0):
    return {"date": f"2026-09-{i:02d}", "temp_max_c": tmax, "temp_min_c": tmin,
            "temp_mean_c": (tmax + tmin) / 2, "precipitation_mm": rain, "et0_mm": et0}


def test_empty_input_gives_empty_summary():
    assert summarize_daily([]) == {}


def test_month_totals_extremes_dry_spell_and_water_balance():
    days = [_day(i) for i in range(1, 31)]
    days[2] = _day(3, tmin=-1.5, rain=12.0)  # a frost night with rain
    days[10] = _day(11, tmax=36.5, rain=0.4)  # a heat day, rain under the 1 mm threshold
    s = summarize_daily(days)
    assert (s["from"], s["to"], s["days_with_data"]) == ("2026-09-01", "2026-09-30", 30)
    assert s["frost_days"] == 1 and s["heat_days"] == 1
    assert s["rain_mm"] == 12.4 and s["rainy_days"] == 1
    assert s["longest_dry_spell_days"] == 27  # day 4 through day 30 without a rainy day
    assert s["et0_mm"] == 120.0 and s["water_balance_mm"] == -107.6
    assert s["temperature_c"]["warmest_max"] == 36.5 and s["temperature_c"]["coldest_min"] == -1.5


def test_last_week_is_compared_with_the_rest_and_listed_day_by_day():
    days = [_day(i, rain=0.0) for i in range(1, 24)] + [_day(i, rain=10.0) for i in range(24, 31)]
    s = summarize_daily(days)
    assert s["last_7_days"]["rain_mm"] == 70.0 and s["previous_days"]["rain_mm"] == 0.0
    assert s["previous_days"]["days"] == 23
    assert [d["date"] for d in s["last_7_days_daily"]] == [f"2026-09-{i:02d}" for i in range(24, 31)]


def test_missing_values_are_tolerated():
    days = [{"date": "2026-09-01", "temp_max_c": None, "temp_min_c": None, "temp_mean_c": None,
             "precipitation_mm": None, "et0_mm": None}]
    s = summarize_daily(days)
    assert s["rain_mm"] is None and s["water_balance_mm"] is None and s["frost_days"] == 0
    assert s["longest_dry_spell_days"] == 0 and s["previous_days"] is None


async def test_nasa_climatology_is_fetched_once_per_grid_cell():
    from unittest.mock import AsyncMock, patch

    from src.providers.weather.nasa_power import NasaPowerAdapter, SolarClimatology

    adapter = NasaPowerAdapter()
    climatology = SolarClimatology(monthly_avg_radiation_mj_m2_day={1: 24.0}, annual_avg_radiation_mj_m2_day=17.0)
    with patch.object(adapter, "_fetch_solar_climatology", AsyncMock(return_value=climatology)) as fetch:
        first = await adapter.solar_climatology(-34.92, -57.95)
        again = await adapter.solar_climatology(-34.94, -57.96)  # same ~55 km cell
        assert first is again is climatology and fetch.await_count == 1
        await adapter.solar_climatology(19.43, -99.13)  # another place -> a new fetch
        assert fetch.await_count == 2
    with patch.object(adapter, "_fetch_solar_climatology", AsyncMock(return_value=None)) as failing:
        await adapter.solar_climatology(40.0, -3.0)
        await adapter.solar_climatology(40.0, -3.0)
        assert failing.await_count == 2  # a failed lookup is retried, not remembered
