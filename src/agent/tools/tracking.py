"""The agent's tracking plan of each lot: read it, write it, correct it.

The plan is the agent's own (the person reads it): stages as estimated windows, key moments, and the checks it will
make or ask for in four sections. It never generates chores or reminders for the person — what to ask and when goes
through the proactive check, paced by the person's tracking intensity. Every correction carries its reason, with
numbers when there are, so the person can see why a window moved."""
from typing import Optional
from uuid import UUID

from src.application.tracking.schemas import PlanRevise, TrackingPlanContent
from src.shared.domain.base import utcnow

from .context import ToolDeps, TurnContext, compact, tool


def _plan_view(plan) -> dict:
    content = plan.content
    return compact({
        "lot_id": str(plan.lot_id), "version": plan.version, "summary": content.summary,
        "current_stage": content.current_stage,
        "stages": [s.model_dump(mode="json", exclude_none=True) for s in content.stages],
        "key_moments": [k.model_dump(mode="json", exclude_none=True) for k in content.key_moments],
        "items": [i.model_dump(mode="json", exclude_none=True) for i in content.items],
        "assumptions": content.assumptions, "missing_context": content.missing_context,
        "last_observation_at": plan.last_observation_at,
        "recent_revisions": [r.model_dump(mode="json", exclude_none=True) for r in plan.revisions[-3:]],
    })


def tracking_read_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def get_tracking_plan(lot_id: str) -> dict:
        """Your tracking plan of a lot: stages (estimated windows, which is current), key moments, the checks by
        section (revision, nutricion_riego, sanidad, proteccion) with their status and results, and the last
        corrections. Read it before answering how a crop is going or what comes next, and before re-planning."""
        plan = await deps.tracking.get(ctx.actor, UUID(lot_id))
        if plan is None:
            return {"lot_id": lot_id, "plan": None,
                    "hint": "No plan yet: plan it with plan_lots_tracking (a background task)."}
        return _plan_view(plan)

    @tool
    async def list_tracking_plans(field: Optional[str] = None) -> dict:
        """Which active lots have a tracking plan, their current stage and the checks due now or overdue."""
        lots = await deps.farm.list_lots(ctx.actor, statuses=["planned", "seedbed", "planted", "growing",
                                                              "harvesting"])
        plans = {p.lot_id: p for p in await deps.tracking.list_plans(ctx.actor, [lot.id for lot in lots])}
        today = utcnow().astimezone(ctx.tz).date()
        due = {}
        for plan, item in await deps.tracking.due_items(ctx.actor, today, plans=list(plans.values())):
            due.setdefault(plan.lot_id, []).append({"item_id": item.id, "title": item.title,
                                                    "window_end": item.window_end})
        return {"lots": [compact({
            "lot_id": str(lot.id), "label": lot.label, "status": lot.status,
            "has_plan": lot.id in plans,
            "current_stage": plans[lot.id].content.current_stage if lot.id in plans else None,
            "due_checks": due.get(lot.id),
        }) for lot in lots]}

    return [get_tracking_plan, list_tracking_plans]


def tracking_write_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def save_tracking_plan(lot_id: str, plan: dict, reason: str) -> dict:
        """Write (or rewrite) a lot's whole tracking plan. `plan`: {summary, current_stage, stages: [{key, name,
        window_start, window_end, status: pendiente|actual|cumplida, signs, risks}], key_moments: [{key, name,
        window_start, window_end, why}], items: [{section: revision|nutricion_riego|sanidad|proteccion, title,
        stage, window_start, window_end, why, how, method: foto|descripcion|medicion|inspeccion|accion,
        measurement, requires_tool, alternative, ask_user}], assumptions, missing_context}. Dates YYYY-MM-DD.
        Windows, not fixed dates. Only checks the person can actually do with their tools and time; scale the
        number of items to their intensity (baja: 4-6, media: 6-10, alta: up to 15). `reason`: why this plan."""
        content = TrackingPlanContent.model_validate(plan)
        saved = await deps.tracking.save(ctx.actor, UUID(lot_id), content, reason)
        return {"saved": True, "version": saved.version, "items": len(saved.content.items)}

    @tool
    async def revise_tracking_plan(
        lot_id: str, reason: str, observation: Optional[str] = None, current_stage: Optional[str] = None,
        stages: Optional[list[dict]] = None, items: Optional[list[dict]] = None,
        new_items: Optional[list[dict]] = None, missing_context: Optional[list[str]] = None,
    ) -> dict:
        """Correct a lot's plan after an observation (a photo analysis, something the person told you, an answer to
        a check, a measurement) or new weather/model data. reason: readable and with numbers when you have them
        («adelanto la floración 5 días: +14 % de GDD acumulado y flores abiertas en la foto»). observation: what
        corrected it. current_stage: the stage key it is in now. stages: [{key, window_start, window_end, status}].
        items: [{id, status: pendiente|pedido|respondido|hecho|descartado, window_start, window_end, result,
        followup_id}]. new_items: like save_tracking_plan's items. Never use it to pile up chores."""
        data = PlanRevise(
            reason=reason, observation=observation, current_stage=current_stage, stages=stages or [],
            items=items or [], new_items=new_items or [], missing_context=missing_context,
        )
        revised = await deps.tracking.revise(ctx.actor, UUID(lot_id), data)
        return {"revised": True, "version": revised.version, "changes": revised.revisions[-1].changes}

    return [save_tracking_plan, revise_tracking_plan]
