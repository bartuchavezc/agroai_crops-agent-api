"""What the person has and how they work, as the agent learns it in the conversation. No catalog: the agent writes
down what the person says, in their words («tester de pH barato», «riego con botellas», «solo los fines de semana»),
so the plan only asks for checks they can actually do."""
from typing import Optional

from .context import ToolDeps, TurnContext, tool


def means_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def update_growing_means(add: Optional[list[dict]] = None, remove: Optional[list[str]] = None,
                                   notes: Optional[str] = None) -> dict:
        """Write down what the person has to work with, as they say it, when it comes up in the conversation: a tool
        or instrument, a material, how they water, their time or budget. add: [{name, note}] in their words
        («tester de pH barato», note «no sabe si está calibrado»); remove: names of things they no longer have.
        notes replaces how they work (time, budget...) — only when they tell you something new about it. Don't ask
        permission to note it; don't invent what they didn't say."""
        if not (add or remove or notes):
            return {"error": "Nothing to note."}
        read = await deps.profiles.update_growing_means(ctx.actor.user_id, add or [], remove or [], notes)
        return {"resources": [r.name for r in read.growing_context.resources], "notes": read.growing_context.notes}

    return [update_growing_means]
