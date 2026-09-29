"""Zone-level satellite status (Sentinel-2/Copernicus): NDVI/NDWI signal, not per-plant precision."""
import logging
from typing import Optional

from google.genai import types

from ..prompts.satellite import SATELLITE_IMAGE_INSTRUCTION
from ..schemas import SatelliteImageAnalysis
from .context import ToolDeps, TurnContext, compact, resolve_field, tool

logger = logging.getLogger(__name__)


def satellite_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_zone_satellite_status(field: Optional[str] = None, include_image: bool = True) -> dict:
        """NDVI/NDWI satellite signal for a field's zone (~500m box, Sentinel-2 — a zone-wide signal like
        the SMN grid, not per-plant precision): whether the zone looks like it's under generalized drought
        or flooding stress, compared against this field's own recent baseline.

        include_image (default true): also fetches the field's latest saved satellite map — reuses the
        existing one if there is one, only renders (and persists) a new one the first time there isn't —
        so this doesn't cost a fresh processing credit on every call. Attaches the image to the chat and
        includes a Gemini-vision interpretation of the color pattern (image_analysis) so you have the full
        picture, not just the NDVI/NDWI numbers, for reasoning."""
        target = await resolve_field(deps, ctx, field)
        status = await deps.satellite.check_field(ctx.actor, target.id)
        result = compact(status)
        if include_image:
            image_identifier = await deps.satellite.get_or_render_image(ctx.actor, target.id)
            if image_identifier:
                ctx.attachments.append(
                    {
                        "type": "zone_map",
                        "image_identifier": image_identifier,
                        "field_id": str(target.id),
                        "caption": f"Mapa NDVI de la zona de {target.name}",
                    }
                )
                result["map_attached"] = True
                try:
                    image_bytes, mime = await deps.satellite.image_bytes_for_model(ctx.actor, image_identifier)
                    analysis: SatelliteImageAnalysis = await deps.gemini.generate_structured(
                        ctx.actor.user_id,
                        contents=[
                            types.Part.from_bytes(data=image_bytes, mime_type=mime),
                            "Interpretá este mapa NDVI de la zona.",
                        ],
                        schema=SatelliteImageAnalysis,
                        system_instruction=SATELLITE_IMAGE_INSTRUCTION,
                    )
                    result["image_analysis"] = compact(analysis)
                except Exception:  # noqa: BLE001 - the numeric status/image are still useful without this
                    logger.exception("Satellite image vision analysis failed")
            else:
                result["map_attached"] = False
        return result

    return [get_zone_satellite_status]
