"""Thermal time: growing degree days (GDD), the clock crops actually run on.

Daily GDD with horizontal cutoffs: max(0, (min(Tmax, Tupper) + max(Tmin, Tbase)) / 2 − Tbase). Base and upper
temperatures are the usual published ones; the GDD to maturity only orients (variety and season change it a lot),
so the agent reads it as one more piece of evidence, never as a calendar."""
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

# crop key -> (Tbase °C, Tupper °C, GDD from sowing/planting to first harvest, rough)
THERMAL: dict[str, tuple[float, float, Optional[float]]] = {
    "tomate": (10, 30, 1300), "pimiento": (10, 30, 1500), "morron": (10, 30, 1500), "berenjena": (10, 32, 1500),
    "zapallo": (10, 32, 1200), "zapallito": (10, 32, 750), "pepino": (10, 32, 800), "melon": (10, 32, 1300),
    "sandia": (10, 32, 1400), "maiz": (10, 30, 1400), "poroto": (10, 30, 1100), "chaucha": (10, 30, 900),
    "lechuga": (4.4, 24, 650), "espinaca": (2, 24, 600), "acelga": (4.4, 26, 700), "rucula": (4.4, 26, 450),
    "repollo": (4.4, 26, 1100), "brocoli": (4.4, 26, 1000), "coliflor": (4.4, 26, 1100), "arveja": (4.4, 26, 900),
    "haba": (4.4, 26, 1100), "cebolla": (4.4, 28, 1700), "ajo": (0, 26, 1900), "zanahoria": (4.4, 28, 1100),
    "rabanito": (4.4, 26, 350), "remolacha": (4.4, 28, 900), "papa": (7, 30, 1300), "frutilla": (5, 30, None),
    "albahaca": (10, 32, 700), "perejil": (4.4, 28, 900), "cilantro": (4.4, 28, 600),
}


def crop_key(name: str) -> str:
    plain = name.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    plain = plain.replace("ñ", "n")
    return next((k for k in THERMAL if k in plain), plain.split()[0] if plain else plain)


def gdd_day(tmin: Optional[float], tmax: Optional[float], tbase: float, tupper: float) -> float:
    if tmin is None or tmax is None:
        return 0.0
    hi = min(tmax, tupper)
    lo = max(tmin, tbase)
    return max(0.0, (hi + lo) / 2 - tbase)


@dataclass
class ThermalTime:
    tbase: float
    tupper: float
    gdd: float
    days: int
    gdd_last_7: float
    gdd_to_harvest: Optional[float]
    progress_percent: Optional[float]
    projected_days_left: Optional[int]
    params_source: str


def accumulate(days: list[dict], tbase: float, tupper: float, gdd_to_harvest: Optional[float],
               forecast: Optional[list[dict]] = None, params_source: str = "tabla") -> ThermalTime:
    """`days`: [{date, tmin, tmax}] since sowing, oldest first; `forecast`: the next days, to project."""
    per_day = [gdd_day(d.get("tmin"), d.get("tmax"), tbase, tupper) for d in days]
    total = sum(per_day)
    last7 = sum(per_day[-7:])
    progress = round(100 * total / gdd_to_harvest, 0) if gdd_to_harvest else None
    left = None
    if gdd_to_harvest and total < gdd_to_harvest:
        rate = (last7 / min(7, len(per_day))) if per_day else 0
        future = [gdd_day(d.get("tmin"), d.get("tmax"), tbase, tupper) for d in forecast or []]
        remaining, count = gdd_to_harvest - total, 0
        for g in future:
            if remaining <= 0:
                break
            remaining -= g
            count += 1
        if remaining > 0 and rate > 0:
            count += math.ceil(remaining / rate)
        left = count if remaining <= 0 or rate > 0 else None
    return ThermalTime(tbase=tbase, tupper=tupper, gdd=round(total, 1), days=len(per_day),
                       gdd_last_7=round(last7, 1), gdd_to_harvest=gdd_to_harvest, progress_percent=progress,
                       projected_days_left=left, params_source=params_source)


def thermal_params(crop_name: str, t_base: Optional[float] = None, t_upper: Optional[float] = None,
                   gdd_to_maturity: Optional[float] = None) -> tuple[float, float, Optional[float], str]:
    """The crop's own parameters (catalog) win; else the table; else a warm-season default."""
    table = THERMAL.get(crop_key(crop_name))
    if t_base is not None:
        return t_base, t_upper or (table[1] if table else 30), gdd_to_maturity or (table[2] if table else None), \
            "catálogo"
    if table:
        return table[0], table[1], gdd_to_maturity or table[2], "tabla"
    return 10.0, 30.0, gdd_to_maturity, "por defecto (cultivo sin parámetros: tomalo con cautela)"


def season_for(day: date, latitude: Optional[float]) -> str:
    """The solar season key of the sun model closest to a date (verano, invierno or equinoccio)."""
    south = latitude is None or latitude < 0
    month = day.month
    summer = month in (11, 12, 1, 2) if south else month in (5, 6, 7, 8)
    winter = month in (5, 6, 7, 8) if south else month in (11, 12, 1, 2)
    return "verano" if summer else "invierno" if winter else "equinoccio"
