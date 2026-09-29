"""Background processing of a layout photo (photo -> AI -> layout objects). Same idea as the diagnosis
report flow: the upload returns immediately with the photo marked "processing"; this runs afterwards and
records either the detected objects or a failure the UI can offer to retry."""
import asyncio
import logging
from uuid import UUID

from src.application.farm.site import site_polygon_m
from src.shared.domain.actor import Actor
from src.shared.utils.errors import CropAnalysisError

from ..tools import ToolDeps
from ..tools.layout import extract_layout_from_photo

logger = logging.getLogger(__name__)

EXTRACTION_TIMEOUT_SECONDS = 150


async def process_layout_photo(deps: ToolDeps, actor: Actor, field_id: UUID, photo_id: str) -> None:
    """Never raises: there is no caller to return an error to, so every failure ends up on the photo itself."""
    objects, camera_xy, error = None, None, None
    try:
        field = await deps.farm.get_field(actor, field_id)
        photo = next((p for p in field.layout_photos if p.id == photo_id), None)
        if photo is None:
            return  # deleted while queued
        objects, camera_xy = await asyncio.wait_for(
            extract_layout_from_photo(deps, actor, photo, site_polygon_m(field)),
            timeout=EXTRACTION_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        error = "El análisis tardó demasiado."
    except CropAnalysisError as e:
        error = e.message
    except Exception:  # noqa: BLE001 - background task, nothing to return the error to
        logger.exception(f"Layout photo {photo_id} processing failed")
        error = "No se pudo analizar la foto."
    try:
        await deps.farm.finish_layout_photo(actor, field_id, photo_id, objects, error, camera_xy)
    except Exception:  # noqa: BLE001
        logger.exception(f"Could not record the result of layout photo {photo_id}")
