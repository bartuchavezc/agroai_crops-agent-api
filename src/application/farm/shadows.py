"""
Geometric sun/shade on the plan. Each element with a height casts a shadow whose length is height / tan(sun
altitude), pointing away from the sun; sampling the terrain over the day tells how many hours of direct sun each
spot gets — the answer to "where do I put each crop", which the 8-octant model can only approximate.

Plan frame: meters, x = East, y = North. Sun azimuth 0 = N, clockwise, so a shadow points along
(-sin(azimuth), -cos(azimuth)).
"""
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .schemas import LayoutObject
from .solar import SunPosition, solar_positions

MAX_SHADOW_M = 80.0  # near sunrise/sunset shadows are effectively infinite; anything longer is capped
_MIN_ALTITUDE_DEG = 1.0  # below this the sun is grazing the horizon: ignore (shade or not, it is barely sun)
_DEFAULT_THICKNESS = 0.5
_TIMELINE_STEP_MINUTES = 30


def footprint(obj: LayoutObject) -> Optional[BaseGeometry]:
    """The element's shape on the ground, or None if it has none."""
    if obj.kind == "circle":
        radius = obj.radius_m or 0.8
        return Point(obj.x_m, obj.y_m).buffer(radius, quad_segs=12)
    if not obj.points:
        return None
    if obj.kind == "polygon":
        shape = Polygon(obj.points)
        return shape if shape.is_valid else shapely.make_valid(shape)
    thickness = obj.thickness_m or _DEFAULT_THICKNESS
    return LineString(obj.points).buffer(thickness / 2, cap_style="flat", join_style="mitre", mitre_limit=2.0)


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def shadow_of(
    obj: LayoutObject, altitude_deg: float, azimuth_deg: float, shape: Optional[BaseGeometry] = None
) -> Optional[BaseGeometry]:
    """Shadow on the ground of one element for one sun position; None if it casts none (flat, or sun too low)."""
    if obj.height_m <= 0 or altitude_deg < _MIN_ALTITUDE_DEG:
        return None
    shape = shape if shape is not None else footprint(obj)
    if shape is None or shape.is_empty:
        return None
    length = min(obj.height_m / math.tan(math.radians(altitude_deg)), MAX_SHADOW_M)
    az = math.radians(azimuth_deg)
    dx, dy = -math.sin(az) * length, -math.cos(az) * length
    moved = shapely.affinity.translate(shape, dx, dy)
    if obj.kind == "circle":
        # A tree is a crown held up by a thin trunk: its shadow is the crown's disc shifted, not a swept solid.
        return moved
    # A solid wall/block: the footprint swept along the shadow vector.
    parts = [shape, moved]
    for polygon in _polygons(shape):
        ring = list(polygon.exterior.coords)
        for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
            quad = Polygon([(x1, y1), (x2, y2), (x2 + dx, y2 + dy), (x1 + dx, y1 + dy)])
            parts.append(quad if quad.is_valid else shapely.make_valid(quad))
    return unary_union(parts)


@dataclass(frozen=True)
class ShadowCaster:
    obj: LayoutObject
    shape: BaseGeometry


def shadow_casters(objects: list[LayoutObject]) -> list[ShadowCaster]:
    casters = []
    for obj in objects:
        if obj.type == "terreno" or obj.height_m <= 0:
            continue
        shape = footprint(obj)
        if shape is not None and not shape.is_empty:
            casters.append(ShadowCaster(obj, shape))
    return casters


def shadows_at(casters: list[ShadowCaster], sun: SunPosition) -> Optional[BaseGeometry]:
    shadows = [s for c in casters if (s := shadow_of(c.obj, sun.altitude_deg, sun.azimuth_deg, c.shape)) is not None]
    return unary_union(shadows) if shadows else None


@dataclass
class SunMoment:
    hour: float
    altitude_deg: float
    azimuth_deg: float
    shadows: list[list[tuple[float, float]]]


@dataclass
class SunMap:
    season: str
    cell_size_m: float
    cells: list[tuple[float, float, float]]  # x, y (cell center), hours of direct sun
    max_hours: float  # the day's length: what a cell in permanent sun would get
    mean_hours: float
    site_area_m2: float
    timeline: list[SunMoment] = field(default_factory=list)


CELL_SIZE_M = 1.0  # the grid the sun hours are counted on: one square meter per cell
MAX_CELLS = 6000  # a huge area gets coarser cells (2 m, 4 m...) instead of an unbounded computation


def _cell_size(area_m2: float, max_cells: int) -> float:
    cell = CELL_SIZE_M
    while area_m2 / (cell * cell) > max_cells:
        cell *= 2
    return cell


Cell = tuple[float, float, float]


def cells_inside(cells: list[Cell], polygon: list[tuple[float, float]]) -> list[Cell]:
    """The cells whose center falls inside `polygon` (e.g. the campo, inside a sun map of the entorno)."""
    if not cells or len(polygon) < 3:
        return []
    shape = Polygon(polygon)
    shape = shape if shape.is_valid else shapely.make_valid(shape)
    xs = np.array([c[0] for c in cells])
    ys = np.array([c[1] for c in cells])
    mask = shapely.contains_xy(shape, xs, ys)
    return [c for c, inside in zip(cells, mask, strict=True) if inside]


def sun_map(
    objects: list[LayoutObject],
    site_points: list[tuple[float, float]],
    latitude: float,
    season: str,
    max_cells: int = MAX_CELLS,
    step_minutes: int = 15,
    include_shadows: bool = False,
) -> SunMap:
    """Hours of direct sun for every 1 m x 1 m cell of the area on the season's representative day: every
    `step_minutes` the shadow of each element is cast over the grid, and a cell earns that step's time if its
    center is not in shadow. `include_shadows` also returns the shadow polygons every 30 minutes."""
    site = Polygon(site_points)
    site = site if site.is_valid else shapely.make_valid(site)
    cell = _cell_size(site.area, max_cells)
    minx, miny, maxx, maxy = site.bounds
    xs = np.arange(minx + cell / 2, maxx, cell)
    ys = np.arange(miny + cell / 2, maxy, cell)
    gx, gy = np.meshgrid(xs, ys)
    gx, gy = gx.ravel(), gy.ravel()
    inside = shapely.contains_xy(site, gx, gy)
    gx, gy = gx[inside], gy[inside]

    casters = shadow_casters(objects)
    sun_hours = np.zeros(len(gx))
    step_hours = step_minutes / 60.0
    positions = solar_positions(latitude, season, step_minutes)
    timeline: list[SunMoment] = []
    every = max(1, _TIMELINE_STEP_MINUTES // step_minutes)

    for i, sun in enumerate(positions):
        shadow = shadows_at(casters, sun)
        if shadow is not None and len(gx):
            shaded = shapely.contains_xy(shadow, gx, gy)
        else:
            shaded = np.zeros(len(gx), dtype=bool)
        if sun.altitude_deg >= _MIN_ALTITUDE_DEG:
            sun_hours += np.where(shaded, 0.0, step_hours)
        if include_shadows and i % every == 0:
            visible = shadow.intersection(site.buffer(MAX_SHADOW_M)) if shadow is not None else None
            timeline.append(
                SunMoment(
                    hour=round(sun.hour, 2),
                    altitude_deg=round(sun.altitude_deg, 1),
                    azimuth_deg=round(sun.azimuth_deg, 1),
                    shadows=[[(round(x, 2), round(y, 2)) for x, y in p.exterior.coords] for p in _polygons(visible)]
                    if visible is not None
                    else [],
                )
            )

    daylight = sum(step_hours for s in positions if s.altitude_deg >= _MIN_ALTITUDE_DEG)
    triples = zip(gx, gy, sun_hours, strict=True)
    cells = [(round(float(x), 2), round(float(y), 2), round(float(h), 2)) for x, y, h in triples]
    return SunMap(
        season=season,
        cell_size_m=cell,
        cells=cells,
        max_hours=round(daylight, 2),
        mean_hours=round(float(sun_hours.mean()), 2) if len(sun_hours) else 0.0,
        site_area_m2=round(site.area, 1),
        timeline=timeline,
    )
