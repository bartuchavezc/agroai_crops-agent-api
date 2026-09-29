"""
Turns the qualitative buckets a vision model can honestly give from a single eye-level photo (left/center/
right, foreground/midground/background) into approximate meters on the top-down plan. A 2D photo carries no
reliable metric depth, so the model is never asked for meters — the numbers come from the fixed scale below,
independent of the plot's own size, and the user finishes the job by dragging objects on the diagram.
"""
import math
import uuid
from typing import TYPE_CHECKING

from .schemas import LayoutObject

if TYPE_CHECKING:  # the guess shape is the agent layer's Gemini output schema; only needed for typing here
    from src.agent.schemas import LayoutObjectGuess

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


def guess_to_layout_object(guess: "LayoutObjectGuess", camera_bearing_degrees: float) -> LayoutObject:
    """camera_bearing_degrees: compass direction the user was facing when taking the photo (0=N, clockwise).
    Returns x_m (East+) / y_m (North+) relative to the camera, i.e. the plot's center."""
    distance = DEPTH_METERS[guess.depth_position]
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
        height_m=guess.estimated_height_m,
        source="photo_ai",
        confidence=guess.confidence,
    )
