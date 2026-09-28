"""Zone-level satellite status (Sentinel-2/Copernicus): NDVI/NDWI signal, not per-plant precision."""
from typing import Optional

from .context import ToolDeps, TurnContext, compact, resolve_field, tool


def satellite_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_zone_satellite_status(field: Optional[str] = None, include_map: bool = False) -> dict:
        """NDVI/NDWI satellite signal for a field's zone (~500m box, Sentinel-2 — a zone-wide signal like
        the SMN grid, not per-plant precision): whether the zone looks like it's under generalized drought
        or flooding stress, compared against this field's own recent baseline. Set include_map=true only
        when the user explicitly asked to see an image (it costs a processing credit each time)."""
        target = await resolve_field(deps, ctx, field)
        status = await deps.satellite.check_field(ctx.actor, target.id)
        result = compact(status)
        if include_map:
            image_identifier = await deps.satellite.render_map_image(ctx.actor, target.id)
            if image_identifier:
                ctx.attachments.append(
                    {
                        "type": "zone_map",
                        "image_identifier": image_identifier,
                        "field_id": str(target.id),
                        "caption": f"Imagen satelital de la zona de {target.name}",
                    }
                )
                result["map_attached"] = True
            else:
                result["map_attached"] = False
        return result

    return [get_zone_satellite_status]
