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


def test_a_lot_counts_the_water_that_reached_it_over_its_zone_area():
    from types import SimpleNamespace
    from uuid import uuid4

    from src.application.irrigation.service import _irrigation_mm

    lettuce, tomato, cantero_1, cantero_2 = uuid4(), uuid4(), uuid4(), uuid4()
    events = [
        # 8 litres on Cantero 1 (4 m²): 2 mm for the lettuce growing there
        SimpleNamespace(quantity=8, unit="litros", zone_id=cantero_1, lot_ids=[lettuce]),
        # 100 litres on Cantero 2, size unknown: spread over the 50 m² field
        SimpleNamespace(quantity=100, unit="litros", zone_id=cantero_2, lot_ids=[tomato]),
        # rain gauge style, the whole field: both lots
        SimpleNamespace(quantity=3, unit="mm", zone_id=None, lot_ids=[lettuce, tomato]),
    ]
    areas = {cantero_1: 4.0}
    assert _irrigation_mm(events, 50.0, lot_id=lettuce, zone_areas=areas) == 5.0
    assert _irrigation_mm(events, 50.0, lot_id=tomato, zone_areas=areas) == 5.0
    # the field as a whole: every litre over the field
    assert _irrigation_mm(events, 50.0) == round(108 / 50 + 3, 1)
