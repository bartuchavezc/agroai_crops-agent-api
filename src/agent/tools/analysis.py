"""Expert analysis tool: the chat runs on a lite model, so interpreting satellite / weather / soil / irrigation
data is delegated here — the field's data is gathered server-side and read by the analysis model chain
(gemini.model_chain), which returns a conclusion for the chat to relay."""
import json
import logging
from datetime import date
from typing import Optional

from .context import ToolDeps, TurnContext, compact, resolve_field, tool

logger = logging.getLogger(__name__)

TOPICS = ("clima", "suelo", "satelital", "riego", "solar")

EXPERT_INSTRUCTION = """Sos un ingeniero agrónomo analizando datos reales de un campo para responder una pregunta
concreta del productor. Usá solo los datos provistos (indicá cuáles), cruzalos entre sí (p. ej. pronóstico + suelo
+ estado satelital), explicá el razonamiento en pocas oraciones y terminá con recomendaciones accionables y su
urgencia. Si faltan datos para concluir algo, decilo. Respondé en español rioplatense, sin inventar valores."""


def analysis_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    async def _gather(topics: list[str], field) -> dict:
        data: dict = {}
        has_coords = field.latitude is not None and field.longitude is not None

        async def safe(name: str, coro):
            try:
                value = await coro
            except Exception as exc:  # noqa: BLE001 - a missing source must not sink the analysis
                logger.warning(f"expert analysis: {name} unavailable: {type(exc).__name__}: {exc}")
                value = None
            if value is not None:
                data[name] = compact(value)

        if "clima" in topics and has_coords:
            await safe("clima_actual", deps.weather.current(field.latitude, field.longitude))
            daily = None
            try:
                daily = await deps.weather.daily_forecast(field.latitude, field.longitude, 4)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"expert analysis: forecast unavailable: {exc}")
            if daily:
                data["pronostico_smn"] = [d.to_dict() for d in daily]
        if "solar" in topics and has_coords:
            climatology = None
            try:
                climatology = await deps.nasa_power.solar_climatology(field.latitude, field.longitude)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"expert analysis: solar unavailable: {exc}")
            if climatology:
                data["radiacion_solar_mj_m2_dia"] = {
                    "mes_actual": climatology.monthly_avg_radiation_mj_m2_day.get(date.today().month),
                    "promedio_anual": climatology.annual_avg_radiation_mj_m2_day,
                }
        if "suelo" in topics and field.soil_context:
            data["suelo_inta"] = compact(field.soil_context)
        if "satelital" in topics:
            await safe("satelital_ndvi_ndwi", deps.satellite.check_field(ctx.actor, field.id))
        if "riego" in topics:
            await safe("riego_et0", deps.irrigation.compute(ctx.actor, field.id))
        return data

    @tool
    async def expert_field_analysis(
        question: str, field: Optional[str] = None, topics: Optional[list[str]] = None
    ) -> dict:
        """In-depth reading of a field's data by the analysis model: use it to interpret satellite (NDVI/NDWI),
        weather/forecast, soil, irrigation or solar data beyond quoting a single value (e.g. "¿conviene regar o
        esperar la lluvia?", "¿por qué el satélite marca estrés?", "¿qué implica este suelo para mis cultivos?").
        topics: any of clima, suelo, satelital, riego, solar (default: all). Relay its conclusion to the user."""
        target = await resolve_field(deps, ctx, field)
        chosen = [t for t in (topics or TOPICS) if t in TOPICS] or list(TOPICS)
        data = await _gather(chosen, target)
        overview = next((o for o in await deps.farm.overview(ctx.actor) if o.field.id == target.id), None)
        crops = ", ".join(
            f"{c.crop_name}{' ' + c.variety if c.variety else ''} ({c.status}"
            f"{', sembrado ' + c.planting_date.isoformat() if c.planting_date else ''})"
            for c in (overview.active_cycles if overview else [])
        ) or "sin cultivos activos"
        prompt = (
            f"{EXPERT_INSTRUCTION}\n\nFecha: {date.today().isoformat()}\nCampo: {target.name}"
            f"{' (' + target.city + ')' if target.city else ''}\nCultivos: {crops}\n"
            f"Pregunta: {question}\n\nDatos disponibles (JSON):\n{json.dumps(data, ensure_ascii=False, default=str)}"
        )
        analysis = await deps.gemini.generate_text(ctx.actor.user_id, prompt, models=deps.gemini.model_chain)
        return {
            "field_name": target.name,
            "topics_with_data": sorted(data),
            "analysis": analysis,
            "model": deps.gemini.model_chain[0],
        }

    return [expert_field_analysis]
