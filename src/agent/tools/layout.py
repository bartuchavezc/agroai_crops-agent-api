"""Photo -> plan elements. Not an agent-callable tool: it's driven by the field page's photo upload (see
reasoning/layout_jobs.py), but it lives here because it's the same shape as the other Gemini-vision helpers
(get_zone_satellite_status): fetch the image, ask for a structured description."""
import io
from typing import Optional

from google.genai import types
from PIL import Image

from src.application.farm.layout_conversion import (
    DEFAULT_CAMERA_HEIGHT_M,
    CameraModel,
    default_camera_position,
    pitch_from_horizon,
    scene_to_layout_objects,
)
from src.application.farm.schemas import LayoutPhoto
from src.shared.domain.actor import Actor

from ..prompts.farm import LAYOUT_EXTRACTION_INSTRUCTION
from ..schemas import PhotoSceneExtraction
from .context import ToolDeps, compact

_MAX_IMAGE_SIDE = 1024

Point = tuple[float, float]


async def extract_layout_from_photo(
    deps: ToolDeps, actor: Actor, photo: LayoutPhoto, site: Optional[list[Point]]
) -> tuple[list[dict], Point]:
    """Returns the plan elements detected in the photo plus the spot where it was taken from.

    Gemini only describes the image (which pixels each thing touches the ground at); the meters come from
    layout_conversion, using the phone's tilt (or the horizon Gemini sees) and the camera height, and the
    user's reference note calibrates the scale."""
    image_bytes, mime = await deps.storage.get_image_for_model(actor, photo.image_identifier, _MAX_IMAGE_SIDE)
    width, height = Image.open(io.BytesIO(image_bytes)).size

    instruction = "Armá el plano de los objetos de este entorno que pueden afectar el sol de la huerta."
    if photo.reference_note and photo.reference_note.strip():
        instruction += f"\n\nNOTA DE REFERENCIA del usuario: {photo.reference_note.strip()}"
    extraction: PhotoSceneExtraction = await deps.gemini.generate_structured(
        actor.user_id,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), instruction],
        schema=PhotoSceneExtraction,
        system_instruction=LAYOUT_EXTRACTION_INSTRUCTION,
    )

    cam = CameraModel(height_m=photo.camera_height_m or DEFAULT_CAMERA_HEIGHT_M, aspect=width / height)
    if photo.pitch_degrees is not None:
        cam = cam.with_pitch(photo.pitch_degrees)  # measured by the phone at the shot
    elif extraction.horizon_y is not None:
        cam = cam.with_pitch(pitch_from_horizon(cam.aspect, extraction.horizon_y))

    if photo.camera_x_m is not None and photo.camera_y_m is not None:
        camera_xy: Point = (photo.camera_x_m, photo.camera_y_m)
    else:
        camera_xy = default_camera_position(site, photo.camera_bearing_degrees)
    objects = scene_to_layout_objects(extraction, cam, photo.camera_bearing_degrees, camera_xy, photo.id)
    return [compact(o) for o in objects], camera_xy
