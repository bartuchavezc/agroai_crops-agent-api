"""
Photo -> plan, in the PHOTO'S OWN FRAME.

Gemini is given the photo plus the measures the user provided for the surroundings (the "entorno": its width, and
its length from where the photo was taken to the far wall) and answers with the plan's polygons in meters, in a
frame it can reason in directly: the camera at (0, 0) looking along +Y, +X to the right of the photo. This module
builds that frame, hands the entorno to the model in it, and converts the answer back to the plan's real frame
(x = East, y = North) using the camera's true-north bearing.

The entorno and the campo (the field's growing plot) are separate elements: they may coincide or not.
"""
import math
import uuid
from typing import TYPE_CHECKING, Optional

from .schemas import LayoutObject
from .site import Point, campo_shape_from_field

if TYPE_CHECKING:  # Gemini's output schema lives in the agent layer; only needed for typing here
    from src.agent.schemas import PlanExtraction

# Nothing the model places is dropped for being far away (the neighbour's trees behind the far wall matter for
# shade), but absurd coordinates are pulled back to this margin around the entorno.
MAX_MARGIN_M = 30.0
_DEFAULT_THICKNESS = {"pared": 0.3, "cerco": 1.0}
_MAX_CROWN_RADIUS_M = 15.0
_MAX_HEIGHT_M = 60.0


def frame_to_enu(point: Point, camera_enu: Point, bearing_deg: float) -> Point:
    """Photo frame (x right of the photo, y forward) -> plan (x East, y North)."""
    psi = math.radians(bearing_deg)
    x, y = point
    return (
        camera_enu[0] + x * math.cos(psi) + y * math.sin(psi),
        camera_enu[1] - x * math.sin(psi) + y * math.cos(psi),
    )


def enu_to_frame(point: Point, camera_enu: Point, bearing_deg: float) -> Point:
    """Inverse of frame_to_enu."""
    psi = math.radians(bearing_deg)
    dx, dy = point[0] - camera_enu[0], point[1] - camera_enu[1]
    return dx * math.cos(psi) - dy * math.sin(psi), dx * math.sin(psi) + dy * math.cos(psi)


def entorno_from_measures(width_m: float, length_m: float, bearing_deg: float) -> tuple[list[Point], Point]:
    """The entorno as the user measured it: `width_m` across the photo, `length_m` from the camera to the far
    wall. Centered on the plan's origin; returns its outline (plan frame) and where the camera stands — the middle
    of the near edge, looking in."""
    corners = [(-width_m / 2, 0.0), (width_m / 2, 0.0), (width_m / 2, length_m), (-width_m / 2, length_m)]
    # place the centre of the rectangle at the origin: the camera is length/2 behind it along the view direction
    psi = math.radians(bearing_deg)
    camera = (-(length_m / 2) * math.sin(psi), -(length_m / 2) * math.cos(psi))
    return [frame_to_enu(c, camera, bearing_deg) for c in corners], camera


def default_camera_position(site: Optional[list[Point]], bearing_deg: float) -> Point:
    """Where the photographer most likely stood on an existing entorno: its edge behind the view direction
    (typically the house, looking into the yard). Falls back to the entorno's center, or the origin."""
    if not site or len(site) < 3:
        return (0.0, 0.0)
    cx = sum(p[0] for p in site) / len(site)
    cy = sum(p[1] for p in site) / len(site)
    psi = math.radians(bearing_deg)
    dx, dy = -math.sin(psi), -math.cos(psi)  # walking backwards from the center
    best: Optional[float] = None
    for a, b in zip(site, site[1:] + site[:1], strict=True):
        ex, ey = b[0] - a[0], b[1] - a[1]
        denom = dx * ey - dy * ex
        if abs(denom) < 1e-12:
            continue
        t = ((a[0] - cx) * ey - (a[1] - cy) * ex) / denom
        s = ((a[0] - cx) * dy - (a[1] - cy) * dx) / denom
        if t > 0 and 0 <= s <= 1 and (best is None or t < best):
            best = t
    if best is None:
        return (cx, cy)
    inset = min(0.5, best * 0.1)
    return (cx + dx * (best - inset), cy + dy * (best - inset))


def polygon_element(element_type: str, label: str, points: list[Point], **extra) -> LayoutObject:
    return LayoutObject(
        id=uuid.uuid4().hex, type=element_type, label=label, kind="polygon", points=points, height_m=0.0, **extra
    )


def campo_element(field, entorno: Optional[list[Point]]) -> Optional[LayoutObject]:
    """The campo drawn from the FIELD's own measures (never from the entorno's), centered inside the entorno by
    default. None if the field has no measures or the plan already has a campo."""
    if any(o.type == "campo" for o in field.layout_objects):
        return None
    shape = campo_shape_from_field(field)
    if not shape:
        return None
    cx, cy = (0.0, 0.0)
    if entorno:
        cx, cy = sum(p[0] for p in entorno) / len(entorno), sum(p[1] for p in entorno) / len(entorno)
    return polygon_element("campo", "Campo", [(round(x + cx, 2), round(y + cy, 2)) for x, y in shape])


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def plan_to_layout_objects(
    extraction: "PlanExtraction",
    camera_enu: Point,
    bearing_deg: float,
    entorno_frame: list[Point],
    photo_id: Optional[str] = None,
) -> list[LayoutObject]:
    """Gemini's elements (photo frame, meters) -> plan elements (East/North). Nothing is filtered out for being
    far; only impossible numbers are pulled back into a margin around the entorno."""
    xs = [p[0] for p in entorno_frame] or [0.0]
    ys = [p[1] for p in entorno_frame] or [0.0]
    x_low, x_high = min(xs) - MAX_MARGIN_M, max(xs) + MAX_MARGIN_M
    y_low, y_high = min(ys) - MAX_MARGIN_M, max(ys) + MAX_MARGIN_M

    def to_plan(x: float, y: float) -> Point:
        fx, fy = _clamp(x, x_low, x_high), _clamp(y, y_low, y_high)
        east, north = frame_to_enu((fx, fy), camera_enu, bearing_deg)
        return round(east, 2), round(north, 2)

    result: list[LayoutObject] = []
    for el in extraction.elements:
        common = dict(
            id=uuid.uuid4().hex,
            type=el.type,
            label=el.label.strip() or el.type,
            height_m=round(_clamp(0.0 if el.type == "pileta" else el.height_m, 0.0, _MAX_HEIGHT_M), 2),
            source="photo_ai",
            confidence=el.confidence,
            photo_id=photo_id,
        )
        if el.kind == "circle" and el.center is not None:
            x, y = to_plan(el.center.x, el.center.y)
            radius = _clamp(el.radius_m or max(0.5, common["height_m"] * 0.3), 0.2, _MAX_CROWN_RADIUS_M)
            result.append(LayoutObject(kind="circle", x_m=x, y_m=y, radius_m=round(radius, 2), **common))
        elif el.kind == "polygon" and el.points and len(el.points) >= 3:
            result.append(LayoutObject(kind="polygon", points=[to_plan(p.x, p.y) for p in el.points], **common))
        elif el.kind == "polyline" and el.points and len(el.points) >= 2:
            thickness = el.thickness_m or _DEFAULT_THICKNESS.get(el.type, 0.5)
            result.append(
                LayoutObject(
                    kind="polyline",
                    points=[to_plan(p.x, p.y) for p in el.points],
                    thickness_m=round(_clamp(thickness, 0.05, 20.0), 2),
                    **common,
                )
            )
    return result
