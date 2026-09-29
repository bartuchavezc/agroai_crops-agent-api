"""Photo -> sun/shade layout objects. Not an agent-callable tool: it's driven by the field form's upload
flow (POST /farm-management/fields/layout/extract), but it lives here because it's the same shape as the
other Gemini-vision helpers (get_zone_satellite_status): fetch the image, ask for a structured guess."""
from google.genai import types

from src.application.farm.layout_conversion import guess_to_layout_object
from src.shared.domain.actor import Actor

from ..prompts.farm import LAYOUT_EXTRACTION_INSTRUCTION
from ..schemas import PhotoLayoutExtraction
from .context import ToolDeps, compact

_MAX_IMAGE_SIDE = 1024


async def extract_layout_from_photo(
    deps: ToolDeps, actor: Actor, image_identifier: str, camera_bearing_degrees: float
) -> list[dict]:
    """camera_bearing_degrees: compass direction the user faced when taking the photo (0=N, clockwise).
    Gemini only gives qualitative positions; the meters come from layout_conversion's fixed scale."""
    image_bytes, mime = await deps.storage.get_image_for_model(actor, image_identifier, _MAX_IMAGE_SIDE)
    extraction: PhotoLayoutExtraction = await deps.gemini.generate_structured(
        actor.user_id,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime),
            "Identificá los objetos de este entorno que pueden afectar el sol de la huerta.",
        ],
        schema=PhotoLayoutExtraction,
        system_instruction=LAYOUT_EXTRACTION_INSTRUCTION,
    )
    return [compact(guess_to_layout_object(g, camera_bearing_degrees)) for g in extraction.objects]
