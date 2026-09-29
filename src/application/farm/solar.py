"""
Deterministic sun/shadow model for a field: real solar position by astronomical formulas (no LLM, no
external API), simplified to 8 compass octants with no real distance/geometry — the "espacio y ambiente"
design explicitly trades survey-grade precision for something a family can reason about with a tape
measure and a compass (see future.md).

Obstacles have no declared distance from the growing area, so blocking is modeled as a height-only
heuristic (`_DEGREES_BLOCKED_PER_METER`): every declared meter of height blocks roughly that many degrees
of low sun coming from its direction. This is a deliberate simplification, not a shadow-casting simulation.
"""
import math
from dataclasses import dataclass
from datetime import date

OCTANTS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
SEASON_DATES: dict[str, date] = {
    # Southern Hemisphere (Argentina): declination is what matters, not the calendar name as such.
    "verano": date(2000, 12, 21),
    "invierno": date(2000, 6, 21),
    "equinoccio": date(2000, 3, 21),
}

_DEGREES_BLOCKED_PER_METER = 6.0
_MAX_BLOCKED_DEGREES = 60.0
_HOUR_ANGLE_STEP_DEG = 3.75  # 16 steps/hour of true solar time


@dataclass(frozen=True)
class Obstacle:
    type: str
    height_m: float
    direction: str


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _declination_deg(day_of_year: int) -> float:
    """Cooper's equation: solar declination for a day of the year, degrees."""
    return 23.45 * math.sin(math.radians(360 / 365 * (284 + day_of_year)))


def _solar_position(latitude_deg: float, declination_deg: float, hour_angle_deg: float) -> tuple[float, float]:
    """Altitude and azimuth (degrees, azimuth 0=N clockwise) for a given latitude/declination/hour angle."""
    lat = math.radians(latitude_deg)
    decl = math.radians(declination_deg)
    ha = math.radians(hour_angle_deg)
    sin_alt = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    altitude = math.degrees(math.asin(_clamp(sin_alt, -1.0, 1.0)))
    alt_rad = math.radians(altitude)
    denom = math.cos(alt_rad) * math.cos(lat)
    cos_az = (math.sin(decl) - math.sin(alt_rad) * math.sin(lat)) / denom if abs(denom) > 1e-9 else 1.0
    azimuth = math.degrees(math.acos(_clamp(cos_az, -1.0, 1.0)))
    if hour_angle_deg > 0:  # afternoon: sun has crossed to the western half
        azimuth = 360 - azimuth
    return altitude, azimuth


def _octant_for_azimuth(azimuth_deg: float) -> str:
    return OCTANTS[round(azimuth_deg / 45) % 8]


def _blocking_altitude_deg(obstacles: list[Obstacle], octant: str) -> float:
    tallest = max((o.height_m for o in obstacles if o.direction == octant), default=0.0)
    return min(tallest * _DEGREES_BLOCKED_PER_METER, _MAX_BLOCKED_DEGREES)


def sun_hours_by_octant(latitude: float, obstacles: list[Obstacle], season: str) -> dict[str, float]:
    """Hours of direct sun attributable to each octant on a representative day of the season, net of any
    obstacle declared in that same direction."""
    day_of_year = SEASON_DATES[season].timetuple().tm_yday
    decl = _declination_deg(day_of_year)
    hours = dict.fromkeys(OCTANTS, 0.0)
    step_hours = _HOUR_ANGLE_STEP_DEG / 15
    hour_angle = -180.0
    while hour_angle < 180.0:
        altitude, azimuth = _solar_position(latitude, decl, hour_angle)
        if altitude > 0:
            octant = _octant_for_azimuth(azimuth)
            if altitude > _blocking_altitude_deg(obstacles, octant):
                hours[octant] += step_hours
        hour_angle += _HOUR_ANGLE_STEP_DEG
    return {k: round(v, 1) for k, v in hours.items()}


@dataclass(frozen=True)
class SunExposureResult:
    by_season: dict[str, dict[str, float]]  # season -> octant -> hours of direct sun


def compute_sun_exposure(
    latitude: float, obstacles: list[Obstacle], seasons: tuple[str, ...] = tuple(SEASON_DATES)
) -> SunExposureResult:
    by_season = {season: sun_hours_by_octant(latitude, obstacles, season) for season in seasons}
    return SunExposureResult(by_season=by_season)


@dataclass(frozen=True)
class SunPosition:
    hour: float  # true solar time, 0-24 (12 = the sun due north/south)
    altitude_deg: float
    azimuth_deg: float  # 0 = N, clockwise


def solar_positions(latitude: float, season: str, step_minutes: int = 15) -> list[SunPosition]:
    """Sun positions while it is above the horizon, on the representative day of the season. Same astronomy as
    sun_hours_by_octant, exposed with the actual altitude/azimuth so shadows can be cast geometrically."""
    decl = _declination_deg(SEASON_DATES[season].timetuple().tm_yday)
    step_ha = step_minutes / 4.0  # 1 minute of time = 0.25 degrees of hour angle
    positions = []
    hour_angle = -180.0
    while hour_angle < 180.0:
        altitude, azimuth = _solar_position(latitude, decl, hour_angle)
        if altitude > 0:
            positions.append(SunPosition(12.0 + hour_angle / 15.0, altitude, azimuth))
        hour_angle += step_ha
    return positions
