"""
Turns the qualitative buckets a vision model can honestly give from a single eye-level photo (left/center/
right, foreground/midground/background) into approximate meters on the top-down plan. A 2D photo carries no
reliable metric depth, so the model is never asked for meters — the numbers come from the fixed scale below,
independent of the plot's own size, and the user finishes the job by dragging objects on the diagram.

When the user also states one real measurement ("the pole is 5 m away and 3 m tall"), that single anchor
rescales the whole scene: the ratio between the stated and the assumed distance/height of that object is
applied to every other object, so relative depth stays consistent but the absolute numbers get grounded.
"""
import math
import uuid
from typing import TYPE_CHECKING

from .schemas import LayoutObject

if TYPE_CHECKING:  # the guess shape is the agent layer's Gemini output schema; only needed for typing here
    from src.agent.schemas import LayoutObjectGuess, PhotoLayoutExtraction

# Assumed distance from the camera (standing at the plot's center) for each depth bucket.
DEPTH_METERS = {"primer_plano": 3.0, "medio": 8.0, "fondo": 15.0}
# Assumed horizontal field of view ~55deg → bucket centers as angular offsets from the camera axis.
HORIZONTAL_OFFSET_DEGREES = {
    "izquierda": -22.0,
    "centro-izquierda": -11.0,
    "centro": 0.0,
    "centro-derecha": 11.0,
    "derecha": 22.0,
}


_MIN_SCALE, _MAX_SCALE = 0.3, 4.0  # a wildly off anchor must not blow the whole diagram out of range


def _clamp_scale(value: float) -> float:
    return max(_MIN_SCALE, min(_MAX_SCALE, value))


def guess_to_layout_object(
    guess: "LayoutObjectGuess",
    camera_bearing_degrees: float,
    distance_scale: float = 1.0,
    height_scale: float = 1.0,
    distance_m: float | None = None,
    height_m: float | None = None,
) -> LayoutObject:
    """camera_bearing_degrees: TRUE-north compass direction the user faced when taking the photo (0=N,
    clockwise). distance_scale/height_scale rescale the assumed bucket distance / estimated height;
    distance_m/height_m override them outright (the user-measured reference object).
    Returns x_m (East+) / y_m (North+) relative to the camera, i.e. the plot's center."""
    distance = distance_m if distance_m is not None else DEPTH_METERS[guess.depth_position] * distance_scale
    height = height_m if height_m is not None else guess.estimated_height_m * height_scale
    offset = math.radians(HORIZONTAL_OFFSET_DEGREES[guess.horizontal_position])
    right_m = distance * math.sin(offset)
    forward_m = distance * math.cos(offset)

    bearing = math.radians(camera_bearing_degrees)
    forward_x, forward_y = math.sin(bearing), math.cos(bearing)  # compass unit vector of the view direction
    right_x, right_y = math.cos(bearing), -math.sin(bearing)  # 90deg clockwise from it

    return LayoutObject(
        id=uuid.uuid4().hex,
        type=guess.type,
        label=guess.label,
        x_m=round(right_m * right_x + forward_m * forward_x, 2),
        y_m=round(right_m * right_y + forward_m * forward_y, 2),
        height_m=round(max(0.0, min(100.0, height)), 2),
        source="photo_ai",
        confidence=guess.confidence,
    )


def layout_objects_from_extraction(
    extraction: "PhotoLayoutExtraction", camera_bearing_degrees: float
) -> list[LayoutObject]:
    """All guesses -> layout objects, calibrated by the user's reference measurement when the model matched
    it to one of the detected objects."""
    objects = extraction.objects
    ref = extraction.reference
    ref_index = ref.object_index if ref and 0 <= ref.object_index < len(objects) else None

    distance_scale = height_scale = 1.0
    if ref is not None and ref_index is not None:
        anchor = objects[ref_index]
        if ref.distance_m:
            distance_scale = _clamp_scale(ref.distance_m / DEPTH_METERS[anchor.depth_position])
        if ref.height_m and anchor.estimated_height_m > 0:
            height_scale = _clamp_scale(ref.height_m / anchor.estimated_height_m)

    result = []
    for i, guess in enumerate(objects):
        is_anchor = i == ref_index and ref is not None
        result.append(
            guess_to_layout_object(
                guess,
                camera_bearing_degrees,
                distance_scale=distance_scale,
                height_scale=height_scale,
                distance_m=ref.distance_m if is_anchor and ref.distance_m else None,
                height_m=ref.height_m if is_anchor and ref.height_m else None,
            )
        )
    return result
