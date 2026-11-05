"""Agronomy models as tools: numbers with their inputs and their uncertainty, for the agent to weigh — never a
verdict. Water in the root zone (FAO-56 bucket, recalibrated by readings), thermal time (GDD), direct sun on a zone
(the field's plan and its shadows) and weather-driven disease risk (TOM-CAST, BLITECAST, oídio, Fulvia, mildiu)."""
from typing import Optional
from uuid import UUID

from .context import ToolDeps, TurnContext, compact, resolve_field, resolve_zone, tool


def agronomy_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_water_balance(lot_id: str) -> dict:
        """Estimated water in a lot's root zone today (FAO-56 bucket): status exceso|ok|regar_pronto|estres,
        % of available water, days to stress at today's demand, and how uncertain it is (it grows with the days since
        the last soil reading). Its assumptions say what it guessed (texture, root depth, waterings without
        amounts). When the uncertainty is large and a decision depends on it, ask for a reading (feel at root depth,
        or a sensor if the person has one) and record it with record_soil_moisture."""
        return compact(await deps.models.water_balance(ctx.actor, UUID(lot_id)))

    @tool
    async def record_soil_moisture(lot_id: str, feel: Optional[str] = None, vwc_percent: Optional[float] = None,
                                   depth_cm: Optional[float] = None, notes: Optional[str] = None) -> dict:
        """A soil-moisture reading of a lot, which recalibrates its water balance: feel (encharcado | muy_humedo |
        humedo | algo_humedo | seco | muy_seco: how the soil feels at root depth, e.g. the finger test at 5-10 cm or
        a handful at 20 cm) or vwc_percent from a probe. Logged in the bitácora as an inspection."""
        return await deps.models.record_soil_moisture(ctx.actor, UUID(lot_id), vwc_percent, feel, depth_cm, notes)

    @tool
    async def get_thermal_time(lot_id: str) -> dict:
        """Growing degree days (GDD) accumulated by a lot since planting (or transplant), the last week's pace, the
        rough GDD to first harvest and a projection with the forecast. Orientative: contrast it with what was seen;
        a shaded zone runs slower than its GDD say (light_note)."""
        return compact(await deps.models.thermal_time(ctx.actor, UUID(lot_id)))

    @tool
    async def get_zone_light(zone: str, field: Optional[str] = None, season: Optional[str] = None) -> dict:
        """Hours of direct sun on a zone ('cantero 2') from the field's plan and its shadows, against open sky, for
        the current season (or verano | invierno | equinoccio). Needs the field's plan (entorno)."""
        target = await resolve_field(deps, ctx, field)
        z = await resolve_zone(deps, ctx, target, zone)
        return compact(await deps.models.zone_light(ctx.actor, z.id, season))

    @tool
    async def get_disease_risk(field: Optional[str] = None, crop: Optional[str] = None,
                               models: Optional[list[str]] = None) -> dict:
        """Weather-driven disease risk for a field over the last 7 days and with the next 3 days of forecast:
        tomcast (tizón temprano/septoriosis), blitecast (tizón tardío), oidio, fulvia (moho foliar), mildiu. Give
        the crop to pick the relevant models. Each comes with its index, level and daily inputs. It is pressure, not
        a diagnosis: use it to decide what to inspect and when."""
        target = await resolve_field(deps, ctx, field)
        return compact(await deps.models.disease_risk(ctx.actor, target.id, crop, models))

    return [get_water_balance, record_soil_moisture, get_thermal_time, get_zone_light, get_disease_risk]
