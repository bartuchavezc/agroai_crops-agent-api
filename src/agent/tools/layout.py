"""Photo -> plan elements. Not an agent-callable tool: it's driven by the field page's photo upload (see
reasoning/layout_jobs.py), but it lives here because it's the same shape as the other Gemini-vision helpers
(get_zone_satellite_status): fetch the image, ask for a structured answer."""
from google.genai import types

from src.application.farm.layout_conversion import (
    campo_element,
    default_camera_position,
    enu_to_frame,
    entorno_from_measures,
    plan_to_layout_objects,
    polygon_element,
)
from src.application.farm.schemas import FieldRead, LayoutPhoto
from src.application.farm.site import Point, environment_polygon_m
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

from ..prompts.farm import LAYOUT_EXTRACTION_INSTRUCTION, format_layout_context
from ..schemas import PlanExtraction
from .context import ToolDeps, compact

_MAX_IMAGE_SIDE = 1280
DEFAULT_CAMERA_HEIGHT_M = 1.5


async def extract_layout_from_photo(
    deps: ToolDeps, actor: Actor, photo: LayoutPhoto, field: FieldRead
) -> tuple[list[dict], Point]:
    """Returns the plan elements to add for this photo plus the spot where it was taken from.

    Gemini gets the photo and the entorno's measures (as the user gave them) and answers with the plan's polygons
    in meters, in the photo's own frame (camera at (0, 0) looking along +Y). The entorno itself comes from the
    user's measures, and the campo from the FIELD's own measures — they are separate elements and never derived
    from each other."""
    bearing = photo.camera_bearing_degrees
    new_elements = []

    entorno = environment_polygon_m(field)  # the user's own (possibly edited) entorno wins
    if entorno:
        camera = (
            (photo.camera_x_m, photo.camera_y_m)
            if photo.camera_x_m is not None and photo.camera_y_m is not None
            else default_camera_position(entorno, bearing)
        )
    else:
        if not (photo.entorno_ancho_m and photo.entorno_largo_m):
            raise InvalidInputError(
                "Faltan las medidas del entorno: indicá el ancho y el largo (desde donde sacaste la foto hasta "
                "la pared del fondo) para armar el plano."
            )
        entorno, default_camera = entorno_from_measures(photo.entorno_ancho_m, photo.entorno_largo_m, bearing)
        camera = (
            (photo.camera_x_m, photo.camera_y_m)
            if photo.camera_x_m is not None and photo.camera_y_m is not None
            else default_camera
        )
        new_elements.append(
            polygon_element("entorno", "Entorno", [(round(x, 2), round(y, 2)) for x, y in entorno], source="manual")
        )

    entorno_frame = [enu_to_frame(p, camera, bearing) for p in entorno]
    context = format_layout_context(
        entorno_frame, photo.camera_height_m or DEFAULT_CAMERA_HEIGHT_M, photo.pitch_degrees, photo.reference_note
    )
    image_bytes, mime = await deps.storage.get_image_for_model(actor, photo.image_identifier, _MAX_IMAGE_SIDE)
    extraction: PlanExtraction = await deps.gemini.generate_structured(
        actor.user_id,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), context],
        schema=PlanExtraction,
        system_instruction=LAYOUT_EXTRACTION_INSTRUCTION,
    )

    objects = plan_to_layout_objects(extraction, camera, bearing, entorno_frame, photo.id)
    campo = campo_element(field, entorno, bearing)
    if campo is not None:
        new_elements.append(campo)
    return [compact(o) for o in [*new_elements, *objects]], camera
