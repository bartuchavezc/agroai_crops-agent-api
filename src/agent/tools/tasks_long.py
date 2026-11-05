"""Background work from the chat: hand the agent a longer job (plan several lots, re-plan one from scratch) and keep
the conversation going while it runs. The person sees its to-do list advance and gets the summary in the chat."""
from typing import Optional
from uuid import UUID

from .context import ToolDeps, TurnContext, compact, tool


def long_task_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def plan_lots_tracking(lot_ids: list[str], replan: bool = False, reason: Optional[str] = None) -> dict:
        """Plan (or re-plan from scratch with replan=true) the tracking of one or more lots in the background:
        a subagent per lot loads the crop sheet and manuals, runs the models and writes your tracking plan. Use it
        after creating lots, or when a lot's plan needs a deep revision. Tell the person in one line that you are
        on it; the result arrives in this chat. For a quick correction use revise_tracking_plan instead."""
        lots = [await deps.farm.get_lot(ctx.actor, UUID(i)) for i in lot_ids]
        if not lots:
            return {"error": "Give at least one lot_id."}
        names = ", ".join(lot.label or str(lot.id)[:8] for lot in lots)
        task = await deps.long_tasks.create(
            ctx.actor, "plan_lots", f"{'Replanificar' if replan else 'Planificar'} el seguimiento: {names}",
            {"lot_ids": [str(lot.id) for lot in lots], "replan": replan, "reason": reason},
            conversation_id=ctx.conversation_id,
        )
        return {"task_id": str(task.id), "status": task.status, "lots": len(lots)}

    @tool
    async def start_long_task(goal: str) -> dict:
        """Start a longer job that needs many steps (e.g. «armá el plan de seguimiento de toda la huerta y
        proponeme las zonas que faltan»). It runs in the background with its own to-do list; any change to the
        person's data comes back as a proposal to confirm. Say in one line that you started it."""
        task = await deps.long_tasks.create(ctx.actor, "general", goal, {}, conversation_id=ctx.conversation_id)
        return {"task_id": str(task.id), "status": task.status}

    @tool
    async def get_task_status(task_id: Optional[str] = None) -> dict:
        """How a background task is going (its to-do list, status and result); without task_id, the open ones of
        this conversation."""
        if task_id:
            task = await deps.long_tasks.get(ctx.actor, UUID(task_id))
            return compact(task.model_dump(mode="json", exclude={"trace"}))
        tasks = await deps.long_tasks.list_tasks(ctx.actor, conversation_id=ctx.conversation_id, open_only=True)
        return {"tasks": [compact(t.model_dump(mode="json", exclude={"trace", "input"})) for t in tasks]}

    return [plan_lots_tracking, start_long_task, get_task_status]
