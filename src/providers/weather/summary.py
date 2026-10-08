"""Aggregates daily weather into the few numbers an agronomist reads from "how was the last month": temperatures,
frost and heat days, rain, dry spells, evapotranspiration and the water balance — plus the last week against the
rest, which is what shows a trend. Pure functions: no I/O."""
from typing import Optional

FROST_C = 0.0  # tmin at or below
HEAT_C = 35.0  # tmax at or above
RAINY_MM = 1.0  # a day with at least this much rain counts as rainy


def _vals(days: list[dict], key: str) -> list[float]:
    return [d[key] for d in days if d.get(key) is not None]


def _round(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _longest_dry_spell(days: list[dict]) -> int:
    best = run = 0
    for d in days:
        if d.get("precipitation_mm") is not None and d["precipitation_mm"] < RAINY_MM:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def _block(days: list[dict]) -> dict:
    rain = _vals(days, "precipitation_mm")
    et0 = _vals(days, "et0_mm")
    return {
        "days": len(days),
        "temp_mean_c": _round(_mean(_vals(days, "temp_mean_c"))),
        "rain_mm": _round(sum(rain)) if rain else None,
        "et0_mm": _round(sum(et0)) if et0 else None,
    }


def summarize_daily(days: list[dict]) -> dict:
    """`days` oldest first, each {date, temp_max_c, temp_min_c, temp_mean_c, precipitation_mm, et0_mm}."""
    if not days:
        return {}
    rain = _vals(days, "precipitation_mm")
    et0 = _vals(days, "et0_mm")
    tmax, tmin = _vals(days, "temp_max_c"), _vals(days, "temp_min_c")
    rain_total = sum(rain) if rain else None
    et0_total = sum(et0) if et0 else None
    last_week, before = days[-7:], days[:-7]
    summary = {
        "from": days[0]["date"],
        "to": days[-1]["date"],
        "days_with_data": len(days),
        "temperature_c": {
            "mean": _round(_mean(_vals(days, "temp_mean_c"))),
            "warmest_max": _round(max(tmax)) if tmax else None,
            "coldest_min": _round(min(tmin)) if tmin else None,
        },
        "frost_days": sum(1 for t in tmin if t <= FROST_C),
        "heat_days": sum(1 for t in tmax if t >= HEAT_C),
        "rain_mm": _round(rain_total),
        "rainy_days": sum(1 for r in rain if r >= RAINY_MM),
        "longest_dry_spell_days": _longest_dry_spell(days),
        "et0_mm": _round(et0_total),
        # rain minus what the atmosphere asked for: negative means the crop lived on irrigation/soil reserve
        "water_balance_mm": (
            _round(rain_total - et0_total) if rain_total is not None and et0_total is not None else None
        ),
        "last_7_days": _block(last_week),
        "previous_days": _block(before) if before else None,
        "last_7_days_daily": [
            {
                "date": d["date"],
                "tmax": _round(d.get("temp_max_c")),
                "tmin": _round(d.get("temp_min_c")),
                "rain_mm": _round(d.get("precipitation_mm")),
            }
            for d in last_week
        ],
    }
    return summary
