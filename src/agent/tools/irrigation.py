"""Irrigation guidance tool: evapotranspiration-based, deterministic (see application/irrigation)."""
from typing import Optional

from .context import ToolDeps, TurnContext, compact, resolve_field, tool


def irrigation_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_irrigation_recommendation(field: Optional[str] = None) -> dict:
        """How much to water a field today: reference evapotranspiration (ET0, FAO-56 Penman-Monteith),
        a field-wide recommendation (whole-plot watering, using the average Kc of active cycles) AND a
        per-cycle breakdown (in case one crop needs more than the rest). Net of recent irrigation events
        already logged and of heavy rain in the forecast. Pure math, not a guess."""
        target = await resolve_field(deps, ctx, field)
        result = await deps.irrigation.compute(ctx.actor, target.id)
        return compact(result)

    return [get_irrigation_recommendation]
