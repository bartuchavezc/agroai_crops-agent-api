"""Agronomy models against their published definitions: FAO-56 bucket, GDD with cutoffs, TOM-CAST and Wallin
tables, the Gubler-Thomas powdery mildew index."""
from datetime import date, timedelta

from src.application.agronomy import disease, thermal, water


def _days(n, et0=5.0, rain=0.0, irrigation=0.0):
    start = date(2026, 11, 1)
    return [water.WaterDay(day=start + timedelta(days=i), et0_mm=et0, rain_mm=rain, irrigation_mm=irrigation)
            for i in range(n)]


def test_taw_and_raw_follow_fao56():
    # loam: θFC 0.25, θWP 0.12, Zr 0.4 m -> TAW = 1000 * 0.13 * 0.4 = 52 mm; p 0.4 -> RAW 20.8 mm
    result = water.simulate([], kc=1.0, texture="franco", root_depth_m=0.4, p=0.4)
    assert (result.taw_mm, result.raw_mm) == (52.0, 20.8)


def test_the_bucket_dries_with_et_and_refills_with_water():
    dry = water.simulate(_days(5, et0=5), kc=1.0, texture="franco", root_depth_m=0.4, p=0.4, start_fraction=0)
    assert dry.status == "estres" and dry.depletion_mm > dry.raw_mm
    wet = water.simulate(_days(5, et0=5, irrigation=6), kc=1.0, texture="franco", root_depth_m=0.4, p=0.4,
                         start_fraction=0)
    assert wet.depletion_mm == 0 and wet.status == "exceso"
    # under a roof the rain doesn't count, outside small rain doesn't either
    assert water.effective_rain(10, covered=True) == 0 and water.effective_rain(1.5, covered=False) == 0


def test_a_reading_recalibrates_and_uncertainty_grows_after_it():
    days = _days(6, et0=4)
    days[1].reading = water.Reading(feel="humedo")
    result = water.simulate(days, kc=1.0, texture="franco", root_depth_m=0.4, p=0.5)
    assert result.days_since_calibration == 4
    uncalibrated = water.simulate(_days(6, et0=4), kc=1.0, texture="franco", root_depth_m=0.4, p=0.5)
    assert uncalibrated.days_since_calibration is None and uncalibrated.uncertainty_mm > result.uncertainty_mm
    probe = water.Reading(vwc_percent=25)  # at field capacity
    assert water.depletion_from_reading(probe, 0.25, 0.12, 0.4, 52) == 0


def test_soil_texture_from_inta_text():
    assert water.texture_from_text("Franco limoso") == "franco_limoso"
    assert water.texture_from_text("arcillo-limosa") == "arcillo_limoso"
    assert water.texture_from_text("Franco arcillo limosa") == "franco_arcillo_limoso"
    assert water.texture_from_text(None) is None


def test_gdd_uses_horizontal_cutoffs():
    assert thermal.gdd_day(8, 20, 10, 30) == 5.0  # (20 + 10) / 2 - 10
    assert thermal.gdd_day(20, 36, 10, 30) == 15.0  # (30 + 20) / 2 - 10
    assert thermal.gdd_day(2, 9, 10, 30) == 0.0
    result = thermal.accumulate([{"tmin": 15, "tmax": 25}] * 10, 10, 30, 200,
                                forecast=[{"tmin": 15, "tmax": 25}] * 3)
    assert result.gdd == 100 and result.progress_percent == 50 and result.projected_days_left == 10
    assert thermal.thermal_params("Tomate cherry")[:2] == (10, 30)
    assert thermal.thermal_params("Lechuga mantecosa", t_base=5)[0] == 5
    assert thermal.season_for(date(2026, 1, 10), -34) == "verano"


def test_tomcast_dsv_table():
    assert disease.tomcast_dsv(5, 15) == 0 and disease.tomcast_dsv(7, 15) == 1 and disease.tomcast_dsv(21, 15) == 3
    assert disease.tomcast_dsv(10, 22) == 2 and disease.tomcast_dsv(21, 22) == 4
    assert disease.tomcast_dsv(10, 35) == 0


def _hours(days, temp, rh, wet_hours):
    out = []
    for d in range(days):
        for h in range(24):
            out.append(disease.Hour(f"2026-11-{d + 1:02d}T{h:02d}:00", temp, rh if h < wet_hours else 60))
    return out


def test_wet_warm_weeks_raise_the_indices():
    wet = _hours(7, 22, 95, 14)
    tomcast = disease.tomcast(wet)
    assert tomcast.index == 7 * 3 and tomcast.level == "alto"
    assert disease.blitecast(wet).level == "alto"
    assert disease.downy_mildew(wet).level == "alto"
    dry = _hours(7, 22, 50, 0)
    assert {r.level for r in disease.run(dry, ["tomcast", "blitecast", "mildiu", "fulvia"])} == {"bajo"}
    assert disease.wallin_sv(18, 20) == 4 and disease.wallin_sv(8, 20) == 0


def test_powdery_mildew_index_climbs_with_warm_days():
    warm = [disease.Hour(f"2026-11-{d + 1:02d}T{h:02d}:00", 25 if 10 <= h < 18 else 15, 60)
            for d in range(4) for h in range(24)]
    risk = disease.powdery_mildew(warm)
    assert risk.index == 80 and risk.level == "alto"
