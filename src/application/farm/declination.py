"""Magnetic declination (WMM): a phone compass points to magnetic north, the solar model needs true north.
Around Argentina the gap is roughly 5-10 degrees west, and it drifts over the years."""
import logging
from datetime import date
from typing import Optional

from pygeomag import GeoMag

logger = logging.getLogger(__name__)

_geomag = GeoMag()


def magnetic_declination_degrees(latitude: float, longitude: float, on: Optional[date] = None) -> float:
    """Degrees east (+) / west (-) that true north lies from magnetic north at this place and date."""
    on = on or date.today()
    decimal_year = on.year + (on.timetuple().tm_yday - 1) / 365.25
    return _geomag.calculate(glat=latitude, glon=longitude, alt=0, time=decimal_year).d


def magnetic_to_true_bearing(
    bearing_degrees: float, latitude: Optional[float], longitude: Optional[float]
) -> float:
    """true = magnetic + declination. Without coordinates (or if the model fails) the bearing is returned
    unchanged — a few degrees off is far below the 45-degree octants the sun model rounds to."""
    if latitude is None or longitude is None:
        return bearing_degrees
    try:
        return (bearing_degrees + magnetic_declination_degrees(latitude, longitude)) % 360
    except Exception:  # noqa: BLE001 - best-effort correction
        logger.exception("Magnetic declination lookup failed")
        return bearing_degrees
