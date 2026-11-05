"""One-tap answers in the chat: when the agent asks something that can be answered with a word, it offers the
options as chips so the person doesn't have to type."""
from .context import ToolDeps, TurnContext, tool


def reply_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def suggest_replies(options: list[str]) -> dict:
        """Offer 2 or 3 one-tap answers (1 to 4 words each: «Sí, regué», «No», «Mañana») for the question you are
        about to ask at the end of your answer. Call it only when a short answer really settles the question."""
        clean = [str(o).strip()[:40] for o in options if str(o).strip()][:3]
        if len(clean) < 2:
            return {"error": "Give 2 or 3 options."}
        ctx.attachments.append({"type": "quick_replies", "options": clean, "caption": ""})
        return {"shown": clean}

    return [suggest_replies]
