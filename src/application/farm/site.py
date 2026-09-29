"""
The two areas on the plan, kept apart on purpose (they may coincide or not):

- ENTORNO: the surroundings seen in the photo — the yard, its walls, hedges, the pool... — with the measures the
  user gave when uploading it (e.g. 18 m across x 42 m from where the photo was taken to the far wall).
- CAMPO: the growing plot, with the FIELD's own measures (length x width, or its traced satellite boundary).

Plan frame: meters, x = East, y = North, origin at the field's coordinates.
"""
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


def _drawn(field: FieldRead, element_type: str) -> Optional[list[Point]]:
    for obj in field.layout_objects:
        if obj.type == element_type and obj.kind == "polygon" and obj.points:
            return list(obj.points)
    return None


def environment_polygon_m(field: FieldRead) -> Optional[list[Point]]:
    """The entorno outline, if the plan has one."""
    return _drawn(field, "entorno")


def campo_polygon_m(field: FieldRead) -> Optional[list[Point]]:
    """The campo outline as drawn on the plan, if the plan has one."""
    return _drawn(field, "campo")


def sun_area_polygon_m(field: FieldRead) -> Optional[list[Point]]:
    """Area the sun map is computed over: the entorno, or — for a plan that only has the plot — the campo."""
    return environment_polygon_m(field) or campo_polygon_m(field)


def campo_shape_from_field(field: FieldRead) -> Optional[list[Point]]:
    """Shape of the campo from the FIELD's own measures, centered on (0, 0): its traced satellite boundary, else
    a rectangle of width_m (across) x length_m (along). None if the field has neither."""
    if field.boundary and len(field.boundary) >= 3 and field.latitude is not None and field.longitude is not None:
        pts = [latlon_to_local_m(lat, lon, field.latitude, field.longitude) for lat, lon in field.boundary]
        cx, cy = polygon_centroid(pts)
        return [(x - cx, y - cy) for x, y in pts]
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
