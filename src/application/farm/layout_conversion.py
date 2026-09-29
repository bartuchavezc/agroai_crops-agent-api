"""
Photo -> plan, by single-view ground-plane geometry.

A vision model can honestly say WHERE things are in a photo (which pixels of the ground an object touches, how
tall it looks) but not how many meters away it is. So Gemini only reports image coordinates, and this module
turns them into meters deterministically: a camera at height `h` looking `pitch` degrees above the horizon
sees a ground point at angle `a` below the horizon at distance `h / tan(a)`. The phone's tilt at the shot
gives the horizon; the user's reference measurement ("the pole is 5 m away") rescales everything at once,
because every distance and height is proportional to the camera height.

Everything here is in the plan's frame: meters, x = East (+), y = North (+), the camera at `camera_xy`.
"""
import math
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .schemas import LayoutObject

if TYPE_CHECKING:  # Gemini's output schema lives in the agent layer; only needed for typing here
    from src.agent.schemas import PhotoSceneExtraction, SceneElementGuess

Point = tuple[float, float]

DEFAULT_CAMERA_HEIGHT_M = 1.5
_MIN_SCALE, _MAX_SCALE = 0.25, 4.0  # a wildly off reference must not blow the whole plan out of range
_DEFAULT_THICKNESS = {"pared": 0.3, "cerco": 1.0}
_FLAT_TYPES = {"pileta"}  # drawn on the ground: they cast no shadow
_MAX_CROWN_RADIUS_M = 12.0


@dataclass(frozen=True)
class CameraModel:
    """Pinhole camera. Image coordinates are normalized (u: 0 left..1 right, v: 0 top..1 bottom); lengths on the
    image plane are measured in units of the image height, so `focal` is too."""

    height_m: float = DEFAULT_CAMERA_HEIGHT_M
    pitch_deg: float = 0.0  # + = looking above the horizon
    aspect: float = 0.75  # image width / height
    diagonal_fov_deg: float = 70.0  # typical phone main camera
    max_distance_m: float = 60.0  # near the horizon the geometry explodes; anything farther is clamped

    @property
    def focal(self) -> float:
        return 0.5 * math.hypot(self.aspect, 1.0) / math.tan(math.radians(self.diagonal_fov_deg) / 2)

    def scaled(self, k: float) -> "CameraModel":
        return CameraModel(self.height_m * k, self.pitch_deg, self.aspect, self.diagonal_fov_deg, self.max_distance_m)

    def with_pitch(self, pitch_deg: float) -> "CameraModel":
        return CameraModel(self.height_m, pitch_deg, self.aspect, self.diagonal_fov_deg, self.max_distance_m)

    def ray(self, u: float, v: float) -> tuple[float, float, float]:
        """Direction of the ray through pixel (u, v) as (right, up, forward), forward being horizontal."""
        xc = (u - 0.5) * self.aspect
        yc = 0.5 - v
        theta = math.radians(self.pitch_deg)
        up = yc * math.cos(theta) + self.focal * math.sin(theta)
        forward = self.focal * math.cos(theta) - yc * math.sin(theta)
        return xc, up, forward


def pitch_from_horizon(aspect: float, horizon_v: float, diagonal_fov_deg: float = 70.0) -> float:
    """Camera pitch that puts the horizon at image row `horizon_v` (used when the phone gave no tilt)."""
    focal = CameraModel(aspect=aspect, diagonal_fov_deg=diagonal_fov_deg).focal
    return math.degrees(math.atan((horizon_v - 0.5) / focal))


def ground_point(cam: CameraModel, u: float, v: float) -> Point:
    """(right_m, forward_m) on the ground of the pixel (u, v), relative to the camera and its heading."""
    right, up, forward = cam.ray(u, v)
    horizontal = math.hypot(right, forward)
    if up < -1e-6 and forward > 1e-6:
        t = cam.height_m / -up
        r, f = right * t, forward * t
        d = math.hypot(r, f)
        if d <= cam.max_distance_m:
            return r, f
        return r * cam.max_distance_m / d, f * cam.max_distance_m / d
    # At or above the horizon (or behind the camera): the ground point is "very far" along that direction.
    scale = cam.max_distance_m / horizontal if horizontal > 1e-9 else 0.0
    return right * scale, max(forward, 1e-6) * scale


def height_above_ground(cam: CameraModel, base: Point, u: float, top_v: float) -> Optional[float]:
    """Height of the thing whose base is `base` (right, forward) and whose top edge shows at pixel (u, top_v)."""
    right, up, forward = cam.ray(u, top_v)
    horizontal = math.hypot(right, forward)
    if horizontal < 1e-9 or forward <= 0:
        return None
    t = math.hypot(*base) / horizontal
    z = cam.height_m + t * up
    return z if 0.05 < z < 100 else None


def to_plan(local: Point, bearing_deg: float, camera_xy: Point) -> Point:
    """Camera-relative (right, forward) -> plan (x East, y North); camera faces `bearing_deg` (true, clockwise)."""
    psi = math.radians(bearing_deg)
    right, forward = local
    x = right * math.cos(psi) + forward * math.sin(psi)
    y = -right * math.sin(psi) + forward * math.cos(psi)
    return camera_xy[0] + x, camera_xy[1] + y


def default_camera_position(site: Optional[list[Point]], bearing_deg: float) -> Point:
    """Where the photographer most likely stood: on the terrain's edge behind the view direction (typically the
    house, looking into the yard). Falls back to the terrain's center, or the plan's origin without a terrain."""
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


@dataclass(frozen=True)
class _Placed:
    guess: "SceneElementGuess"
    ground: list[Point]  # camera-relative (right, forward) for each ground point
    height: Optional[float]  # from the top edge, when it could be measured


def _place(cam: CameraModel, guess: "SceneElementGuess") -> _Placed:
    ground = [ground_point(cam, p.x, p.y) for p in guess.ground_points]
    height = None
    if guess.top_y is not None and guess.ground_points and guess.top_y < guess.ground_points[0].y:
        height = height_above_ground(cam, ground[0], guess.ground_points[0].x, guess.top_y)
    return _Placed(guess, ground, height)


def _calibration_scale(cam: CameraModel, extraction: "PhotoSceneExtraction") -> float:
    """Factor k such that the user's stated distance/height of one object matches what the geometry says."""
    ref = extraction.reference
    if ref is None or not (0 <= ref.object_index < len(extraction.elements)):
        return 1.0
    anchor = _place(cam, extraction.elements[ref.object_index])
    if ref.distance_m and anchor.ground:
        nearest = min(math.hypot(*p) for p in anchor.ground)
        if nearest > 0.5:
            return max(_MIN_SCALE, min(_MAX_SCALE, ref.distance_m / nearest))
    if ref.height_m and anchor.height:
        return max(_MIN_SCALE, min(_MAX_SCALE, ref.height_m / anchor.height))
    return 1.0


def scene_to_layout_objects(
    extraction: "PhotoSceneExtraction",
    cam: CameraModel,
    bearing_deg: float,
    camera_xy: Point,
    photo_id: Optional[str] = None,
) -> list[LayoutObject]:
    """Gemini's image-space elements -> plan elements in meters, calibrated by the user's reference note."""
    cam = cam.scaled(_calibration_scale(cam, extraction))
    ref = extraction.reference
    ref_index = ref.object_index if ref and 0 <= ref.object_index < len(extraction.elements) else None

    result: list[LayoutObject] = []
    for i, guess in enumerate(extraction.elements):
        placed = _place(cam, guess)
        if not placed.ground:
            continue
        height = placed.height if placed.height is not None else guess.estimated_height_m
        if i == ref_index and ref is not None and ref.height_m:
            height = ref.height_m
        if guess.type in _FLAT_TYPES:
            height = 0.0
        height = round(max(0.0, min(100.0, height)), 2)
        points = [tuple(round(c, 2) for c in to_plan(p, bearing_deg, camera_xy)) for p in placed.ground]
        common = dict(
            id=uuid.uuid4().hex,
            type=guess.type,
            label=guess.label,
            height_m=height,
            source="photo_ai",
            confidence=guess.confidence,
            photo_id=photo_id,
        )
        if guess.kind == "circle":
            x, y = points[0]
            radius = _crown_radius(cam, guess, placed.ground[0], height)
            result.append(LayoutObject(kind="circle", x_m=x, y_m=y, radius_m=radius, **common))
        elif guess.kind == "polygon" and len(points) >= 3:
            result.append(LayoutObject(kind="polygon", points=points, **common))
        elif guess.kind == "polyline" and len(points) >= 2:
            thickness = _DEFAULT_THICKNESS.get(guess.type, 0.5)
            result.append(LayoutObject(kind="polyline", points=points, thickness_m=thickness, **common))
    return result


def _crown_radius(cam: CameraModel, guess: "SceneElementGuess", ground: Point, height_m: float) -> float:
    """Crown radius of a tree: its width on the image, scaled by how far it is; else a proportion of its height."""
    if guess.crown_width:
        distance = math.hypot(ground[0], ground[1], cam.height_m)
        width_m = guess.crown_width * cam.aspect / cam.focal * distance
        return round(max(0.3, min(_MAX_CROWN_RADIUS_M, width_m / 2)), 2)
    return round(max(0.5, min(_MAX_CROWN_RADIUS_M, height_m * 0.3)), 2)
