from datetime import date

from src.application.irrigation.service import next_irrigation

TODAY = date(2026, 10, 9)


def test_due_today_when_the_balance_already_calls_for_water():
    assert next_irrigation(4.26, 4.0, "regar", [0, 0, 0], TODAY) == (TODAY, 4.3)
    assert next_irrigation(-1.0, 4.0, "regar", [], TODAY) == (TODAY, 0.0)


def test_the_balance_builds_up_day_by_day_and_rain_postpones_it():
    # covered today (net 0): demand 3 mm/day crosses the 2 mm threshold tomorrow
    assert next_irrigation(0.0, 3.0, "cubierto", [0, 0, 0, 0], TODAY) == (date(2026, 10, 10), 3.0)
    # 10 mm of rain tomorrow: balance -7, -4, -1, 2 (not above the threshold yet), 5 on the fifth day
    assert next_irrigation(0.0, 3.0, "cubierto", [0, 10, 0, 0, 0], TODAY) == (date(2026, 10, 14), 5.0)


def test_heavy_rain_today_counts_against_the_balance_and_no_need_gives_null():
    # today's rain (50 mm) soaks the soil: demand of 4 mm/day takes more than the horizon to bring it back
    assert next_irrigation(1.0, 4.0, "no_regar_lluvia", [50, 0, 0, 0, 0, 0, 0], TODAY) == (None, None)
    # constant rain covering the demand every day: never due within the horizon
    assert next_irrigation(0.0, 3.0, "cubierto", [4] * 7, TODAY) == (None, None)
    # without a forecast, only the demand counts
    assert next_irrigation(0.0, 3.0, "cubierto", [], TODAY) == (date(2026, 10, 10), 3.0)
