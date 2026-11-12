"""Root-zone water balance, FAO-56 single bucket (Allen et al. 1998, chapter 8).

Depletion Dr (mm below field capacity) moves each day by: Dr = Dr_prev - effective rain - irrigation + ETc·Ks, never
below 0 (excess drains) nor above TAW. TAW = 1000·(θFC − θWP)·Zr, RAW = p·TAW; when Dr > RAW the crop is stressed
(Ks < 1). A field reading — a probe in % of volume, or the feel of the soil at root depth — resets Dr: the estimate
is only as good as its last calibration, and the uncertainty grows with every day since."""
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

# FAO-56 table 19, mid values (m³/m³). A potting substrate holds more and drains better.
TEXTURES: dict[str, tuple[float, float]] = {
    "arenoso": (0.12, 0.045), "arenoso_franco": (0.14, 0.06), "franco_arenoso": (0.23, 0.10),
    "franco": (0.25, 0.12), "franco_limoso": (0.29, 0.15), "limoso": (0.32, 0.17),
    "franco_arcillo_limoso": (0.34, 0.21), "franco_arcilloso": (0.32, 0.20), "arcillo_limoso": (0.36, 0.23),
    "arcilloso": (0.36, 0.22), "sustrato": (0.40, 0.10),
}
# Effective root depth (m) by where it grows: a pot or a box caps it whatever the crop.
ROOT_DEPTH_BY_ZONE = {"maceta": 0.2, "cajon": 0.3, "hidroponia": 0.15, "cantero": 0.4, "invernadero": 0.45,
                      "tierra_directa": 0.5}
# Depletion fraction p (FAO-56 table 22) for common crops; 0.5 otherwise.
P_BY_CROP = {"lechuga": 0.3, "espinaca": 0.2, "cebolla": 0.3, "ajo": 0.3, "tomate": 0.4, "pimiento": 0.3,
             "morron": 0.3, "berenjena": 0.45, "zapallo": 0.35, "zapallito": 0.5, "pepino": 0.5, "frutilla": 0.2,
             "papa": 0.35, "zanahoria": 0.35, "rabanito": 0.3, "acelga": 0.35, "brocoli": 0.45, "repollo": 0.45,
             "maiz": 0.5, "poroto": 0.45, "arveja": 0.35, "albahaca": 0.4, "melon": 0.4, "sandia": 0.4}
FEEL: dict[str, float] = {  # the feel of the soil at root depth -> fraction of TAW depleted
    "encharcado": 0.0, "muy_humedo": 0.05, "humedo": 0.2, "algo_humedo": 0.45, "seco": 0.75, "muy_seco": 0.95,
}
Status = Literal["exceso", "ok", "regar_pronto", "estres"]


def texture_from_text(text: Optional[str]) -> Optional[str]:
    """INTA's surface texture ("Franco limoso", "arcillo-limosa") to a key of TEXTURES."""
    if not text:
        return None
    t = text.lower().replace("-", " ").replace("á", "a").replace("ó", "o")
    has = {k: k in t for k in ("arcill", "lim", "aren", "franc")}
    if has["franc"]:
        if has["arcill"] and has["lim"]:
            return "franco_arcillo_limoso"
        if has["arcill"]:
            return "franco_arcilloso"
        if has["lim"]:
            return "franco_limoso"
        if has["aren"]:
            return "franco_arenoso"
        return "franco"
    if has["arcill"]:
        return "arcillo_limoso" if has["lim"] else "arcilloso"
    if has["aren"]:
        return "arenoso"
    if has["lim"]:
        return "limoso"
    return None


@dataclass
class WaterDay:
    day: date
    et0_mm: float
    rain_mm: float = 0.0
    irrigation_mm: float = 0.0
    reading: Optional["Reading"] = None  # a calibration taken that day (applied at the end of it)


@dataclass
class Reading:
    vwc_percent: Optional[float] = None  # a probe, % volume
    feel: Optional[str] = None  # a key of FEEL


@dataclass
class WaterBalance:
    taw_mm: float
    raw_mm: float
    depletion_mm: float
    status: Status
    uncertainty_mm: float
    days_since_calibration: Optional[int]
    days_to_raw: Optional[int]  # at today's demand, days until it reaches the stress threshold
    etc_mm_today: float
    series: list[dict] = field(default_factory=list)

    @property
    def moisture_percent_of_available(self) -> float:
        return round(100 * (1 - self.depletion_mm / self.taw_mm), 0) if self.taw_mm else 0.0


def effective_rain(rain_mm: float, covered: bool) -> float:
    """Light rain wets the canopy and evaporates; under a roof none arrives."""
    if covered or rain_mm < 2:
        return 0.0
    return rain_mm * 0.8 if rain_mm > 25 else rain_mm


def depletion_from_reading(reading: Reading, fc: float, wp: float, zr: float, taw: float) -> Optional[float]:
    if reading.vwc_percent is not None:
        theta = reading.vwc_percent / 100
        return max(0.0, min(taw, 1000 * (fc - theta) * zr))
    if reading.feel in FEEL:
        return FEEL[reading.feel] * taw
    return None


def simulate(days: list[WaterDay], kc: float, texture: str, root_depth_m: float, p: float = 0.5,
             covered: bool = False, start_fraction: float = 0.3) -> WaterBalance:
    """Run the bucket over `days` (oldest first). Without a reading it starts at `start_fraction` of TAW depleted
    and says so through a wide uncertainty."""
    fc, wp = TEXTURES.get(texture, TEXTURES["franco"])
    taw = 1000 * (fc - wp) * root_depth_m
    raw = p * taw
    dr = start_fraction * taw
    since: Optional[int] = None
    series = []
    etc = 0.0
    for d in days:
        ks = 1.0 if dr <= raw else max(0.0, (taw - dr) / ((1 - p) * taw)) if taw else 1.0
        etc = kc * d.et0_mm
        dr = dr - effective_rain(d.rain_mm, covered) - d.irrigation_mm + ks * etc
        dr = max(0.0, min(taw, dr))
        if d.reading is not None:
            calibrated = depletion_from_reading(d.reading, fc, wp, root_depth_m, taw)
            if calibrated is not None:
                dr, since = calibrated, 0
        elif since is not None:
            since += 1
        series.append({"date": d.day.isoformat(), "depletion_mm": round(dr, 1), "et0_mm": d.et0_mm,
                       "rain_mm": d.rain_mm, "irrigation_mm": d.irrigation_mm})
    if since is None:
        uncertainty = taw * 0.35
    else:
        uncertainty = min(taw * 0.5, 2.0 + 0.6 * since * max(etc, 1.0))
    status: Status = "exceso" if dr < 0.05 * taw else "ok" if dr <= 0.75 * raw else \
        "regar_pronto" if dr <= raw else "estres"
    days_to_raw = None
    if etc > 0 and dr < raw:
        days_to_raw = int((raw - dr) // etc)
    return WaterBalance(
        taw_mm=round(taw, 1), raw_mm=round(raw, 1), depletion_mm=round(dr, 1), status=status,
        uncertainty_mm=round(uncertainty, 1), days_since_calibration=since, days_to_raw=days_to_raw,
        etc_mm_today=round(etc, 2), series=series[-14:],
    )
