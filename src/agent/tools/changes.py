"""Proposals: several writes prepared by the agent and shown to the user, who applies (or unticks, or rejects) them
from the chat. Nothing changes until then."""
from src.application.changes.schemas import Operation

from .context import ToolDeps, TurnContext, compact, tool


def change_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def propose_changes(title: str, operations: list[dict]) -> dict:
        """Prepare several writes in ONE proposal the user reviews and confirms in the chat's side panel. Use it to
        create, edit or delete more than one thing at once (lots, their status or dates, zones and their numbers,
        seed lots, tasks, reminders, plans, plan crops, stages, bitácora entries) and for ANY delete.
        operations: [{op: create|update|delete, entity: zone|lot|event|seed_lot|task|reminder|plan|plan_crop|stage,
        id?: (update/delete), data: {...}}] — data uses the API fields (ids, YYYY-MM-DD dates): lot {field_id,
        crop_master_id, zone_ids, season, number, status, planting_date, quantity, unit...}; zone {field_id, type,
        number, name, length_m, width_m}; task {title, zone_id, lot_id, due_date, assigned_to, result_event_type};
        reminder {title, due_at, recurrence, interval_days, zone_id}; seed_lot {crop_master_id, quantity, unit};
        plan_crop {plan_id, crop_master_id, mode, start_date, count, every_days}; stage {plan_id, name, stage,
        start_date}. "$N" in id or data = the id operation N (0-based) creates.
        Returns the preview with any error per operation; fix them and propose again before telling the user.
        Then tell the user, in one or two lines, what you proposed: they confirm it in the panel."""
        ops = [Operation(**o) for o in operations]
        proposal = await deps.changes.propose(ctx.actor, title, ops, conversation_id=ctx.conversation_id)
        errors = [i for i in proposal.preview if i.error]
        if not errors:
            ctx.attachments.append({"type": "proposal", "proposal_id": str(proposal.id), "caption": title})
        return {
            "proposal_id": str(proposal.id),
            "shown_to_user": not errors,
            "items": compact([{"index": i.index, "title": i.title, "error": i.error} for i in proposal.preview]),
        }

    return [propose_changes]
