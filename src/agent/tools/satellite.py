"""Field satellite status and time series (Copernicus Sentinel-2 + Sentinel-1): read against the field's own
history, a lot/zone-level signal (10 m pixels), not per-plant precision."""
import logging
from datetime import date, timedelta
from typing import Optional

from google.genai import types

from ..prompts.satellite import SATELLITE_IMAGE_INSTRUCTION, SATELLITE_SERIES_GUIDE
from ..schemas import SatelliteImageAnalysis
from .context import ToolDeps, TurnContext, compact, resolve_field, tool

logger = logging.getLogger(__name__)


def satellite_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_zone_satellite_status(field: Optional[str] = None, include_image: bool = True) -> dict:
        """How the field is doing by satellite, read against ITS OWN history (Sentinel-2 every ~5 days since
        up to several years back, Sentinel-1 radar for cloudy stretches; the drawn boundary, or a ~500m box
        when there is none). `analysis` has: the last cloud-free pass (date, how much of the field was
        clear, NDVI/NDRE/NDMI/EVI/NDWI), each index smoothed vs its normal for this week (p10/p50/p90 of
        previous years) and vs last year, the 15-day trend, the season stage (pre_brote / crecimiento /
        pico / caida / fin_de_ciclo, with green-up and peak dates vs last year's peak), a radar signal when
        the optical has a cloud gap, and `caveats`. `alerts` are the rules that fired ("va peor que lo
        normal", "peor que el año pasado", caída anticipada, estrés hídrico, anegamiento). Read
        `interpretation_guide` before concluding.

        include_image (default true): also fetches the field's latest saved satellite map — reuses the
        existing one if there is one, only renders (and persists) a new one the first time there isn't —
        so this doesn't cost a fresh processing credit on every call. Attaches the image to the chat and
        includes a Gemini-vision interpretation of the color pattern (image_analysis) so you have the full
        picture, not just the NDVI/NDWI numbers, for reasoning."""
        target = await resolve_field(deps, ctx, field)
        status = await deps.satellite.check_field(ctx.actor, target.id)
        result = compact(status)
        result["interpretation_guide"] = SATELLITE_SERIES_GUIDE
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
                    image_bytes, mime = await deps.satellite.image_bytes_for_model(
                        ctx.actor, image_identifier, field=target
                    )
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

    @tool
    async def get_field_satellite_series(
        field: Optional[str] = None, metric: str = "ndvi", months: int = 12
    ) -> dict:
        """Week-by-week satellite series of one index for a field over the last `months` (max 60): each
        week's clear-pass mean (`raw`, null when clouds hid it), the smoothed curve, this field's normal band
        for that week (normal_p10/p50/p90 across previous years, null with < 2 years of history) and last
        year's value. Use it to describe the season's shape ("arrancó más tarde", "el pico fue más bajo que
        el año pasado", "viene cayendo hace 3 semanas") or answer "¿cómo viene comparado con otros años?".
        metric: ndvi (verdor), ndre (vigor en canopeo denso), ndmi (agua en el canopeo), evi, ndwi (agua
        libre). Stored data only, no new satellite request."""
        target = await resolve_field(deps, ctx, field)
        months = max(1, min(int(months), 60))
        data = await deps.satellite.series(
            ctx.actor, target.id, metric=metric, since=date.today() - timedelta(days=30 * months)
        )
        data.pop("passes", None)  # the weekly table already summarizes them; keeps the result short
        radar = data.pop("radar_passes", [])
        if radar:
            data["radar_last_passes"] = radar[-6:]
        return compact(data)

    @tool
    async def compare_fields_satellite() -> dict:
        """All the account's fields read against their own satellite history, most anomalous first: last
        clear pass, smoothed NDVI, difference vs its normal for this week and vs last year, trend and season
        stage. Use it for "¿cuál de mis campos está peor?" or a quick satellite overview. Stored data only."""
        rows = await deps.satellite.compare_fields(ctx.actor)
        note = "vs_normal/vs_last_year: diferencia de NDVI suavizado; ±0.05 es ruido."
        return {"fields": compact(rows), "note": note}

    return [get_zone_satellite_status, get_field_satellite_series, compare_fields_satellite]
