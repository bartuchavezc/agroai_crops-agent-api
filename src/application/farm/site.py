"""The field's terrain as a polygon in the plan's local meters (origin = the field's coordinates, x = East,
y = North). Shared by the photo->plan conversion (where the camera stands) and the sun/shade maps."""
import math
from typing import Optional

from .schemas import FieldRead

_METERS_PER_DEGREE_LAT = 110_540.0
_METERS_PER_DEGREE_LON_AT_EQUATOR = 111_320.0

Point = tuple[float, float]


def latlon_to_local_m(latitude: float, longitude: float, origin_lat: float, origin_lon: float) -> Point:
    """Small-area equirectangular projection: accurate to centimeters over the few hundred meters of a field."""
    x = (longitude - origin_lon) * _METERS_PER_DEGREE_LON_AT_EQUATOR * math.cos(math.radians(origin_lat))
    y = (latitude - origin_lat) * _METERS_PER_DEGREE_LAT
    return x, y


def site_polygon_m(field: FieldRead) -> Optional[list[Point]]:
    """Terrain outline, in order of preference: a "terreno" element drawn on the plan, the boundary traced
    over the satellite image, or a length x width rectangle centered on the field. None if there is nothing
    to build one from."""
    for obj in field.layout_objects:
        if obj.type == "terreno" and obj.kind == "polygon" and obj.points:
            return list(obj.points)
    if field.boundary and field.latitude is not None and field.longitude is not None:
        return [latlon_to_local_m(lat, lon, field.latitude, field.longitude) for lat, lon in field.boundary]
    if field.length_m and field.width_m:
        half_w, half_l = field.width_m / 2, field.length_m / 2
        return [(-half_w, -half_l), (half_w, -half_l), (half_w, half_l), (-half_w, half_l)]
    return None


def polygon_area(points: list[Point]) -> float:
    """Shoelace area (m2), always positive."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1], strict=True):
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def polygon_centroid(points: list[Point]) -> Point:
    """Vertex average: plenty for choosing where to stand; not the area centroid."""
    return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
