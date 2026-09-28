"""
FAO-56 Penman-Monteith reference evapotranspiration (ET0), daily time step. Standard formula
(Allen et al., 1998, FAO Irrigation and Drainage Paper 56, Chapter 4) — pure math, no LLM, no external
call. Elevation is not collected from the user, so atmospheric pressure/psychrometric constant use the
sea-level default (fine for the Argentine pampas/urban gardens this app targets; a mountain field would
see a small underestimate of ET0).
"""
import math
from dataclasses import dataclass
from typing import Optional

_SIGMA = 4.903e-9  # Stefan-Boltzmann constant, MJ K^-4 m^-2 day^-1
_GSC = 0.0820  # solar constant, MJ m^-2 min^-1
_ALBEDO = 0.23  # reference crop (grass) albedo
_SEA_LEVEL_PRESSURE_KPA = 101.3
_PSYCHROMETRIC_CONSTANT = 0.000665 * _SEA_LEVEL_PRESSURE_KPA  # kPa/°C, at sea level


def _saturation_vapor_pressure(temp_c: float) -> float:
    return 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))


def _slope_svp_curve(temp_c: float) -> float:
    es = _saturation_vapor_pressure(temp_c)
    return (4098 * es) / (temp_c + 237.3) ** 2


def _extraterrestrial_radiation_mj(latitude_deg: float, day_of_year: int) -> float:
    """Ra: daily extraterrestrial radiation, MJ/m2/day."""
    lat = math.radians(latitude_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * day_of_year)
    decl = 0.409 * math.sin(2 * math.pi / 365 * day_of_year - 1.39)
    x = 1 - (math.tan(lat) ** 2) * (math.tan(decl) ** 2)
    x = max(x, 1e-9)
    sunset_hour_angle = math.pi / 2 - math.atan(-math.tan(lat) * math.tan(decl) / math.sqrt(x))
    return (
        (24 * 60 / math.pi)
        * _GSC
        * dr
        * (
            sunset_hour_angle * math.sin(lat) * math.sin(decl)
            + math.cos(lat) * math.cos(decl) * math.sin(sunset_hour_angle)
        )
    )


def wind_speed_2m(wind_speed_10m_ms: float) -> float:
    """Standard log-wind-profile conversion from a 10m measurement to the FAO-56 reference height (2m)."""
    return wind_speed_10m_ms * 0.748


@dataclass(frozen=True)
class Et0Inputs:
    latitude: float
    day_of_year: int
    tmax_c: float
    tmin_c: float
    mean_humidity_pct: float
    wind_speed_2m_ms: float
    shortwave_radiation_mj_m2_day: float


def reference_et0_mm(inputs: Et0Inputs) -> float:
    """ET0 in mm/day for a reference well-watered grass surface."""
    t_mean = (inputs.tmax_c + inputs.tmin_c) / 2
    delta = _slope_svp_curve(t_mean)
    gamma = _PSYCHROMETRIC_CONSTANT

    es = (_saturation_vapor_pressure(inputs.tmax_c) + _saturation_vapor_pressure(inputs.tmin_c)) / 2
    ea = _saturation_vapor_pressure(t_mean) * (inputs.mean_humidity_pct / 100)

    ra = _extraterrestrial_radiation_mj(inputs.latitude, inputs.day_of_year)
    rso = 0.75 * ra  # clear-sky radiation, elevation term dropped (no elevation input)
    rs = max(0.0, inputs.shortwave_radiation_mj_m2_day)
    rns = (1 - _ALBEDO) * rs
    rs_rso_ratio = min(rs / rso, 1.0) if rso > 0 else 0.0
    tmax_k4 = (inputs.tmax_c + 273.16) ** 4
    tmin_k4 = (inputs.tmin_c + 273.16) ** 4
    rnl = (
        _SIGMA
        * ((tmax_k4 + tmin_k4) / 2)
        * (0.34 - 0.14 * math.sqrt(max(ea, 0.0)))
        * (1.35 * rs_rso_ratio - 0.35)
    )
    rn = rns - rnl

    u2 = inputs.wind_speed_2m_ms
    numerator = 0.408 * delta * rn + gamma * (900 / (t_mean + 273)) * u2 * max(es - ea, 0.0)
    denominator = delta + gamma * (1 + 0.34 * u2)
    return max(0.0, numerator / denominator)


def build_et0_inputs(
    latitude: float,
    day_of_year: int,
    tmax_c: Optional[float],
    tmin_c: Optional[float],
    humidity_pct: Optional[float],
    wind_speed_10m_ms: Optional[float],
    radiation_w_m2: Optional[float],
) -> Optional[Et0Inputs]:
    """None when the minimum inputs aren't available (missing SMN/Open-Meteo data for the point)."""
    if tmax_c is None or tmin_c is None:
        return None
    # W/m2 average over the day -> MJ/m2/day: W/m2 * 86400 s/day / 1e6 J/MJ
    radiation_mj = (radiation_w_m2 * 0.0864) if radiation_w_m2 is not None else 0.0
    return Et0Inputs(
        latitude=latitude,
        day_of_year=day_of_year,
        tmax_c=tmax_c,
        tmin_c=tmin_c,
        mean_humidity_pct=humidity_pct if humidity_pct is not None else 60.0,
        wind_speed_2m_ms=wind_speed_2m(wind_speed_10m_ms if wind_speed_10m_ms is not None else 2.0),
        shortwave_radiation_mj_m2_day=radiation_mj,
    )
