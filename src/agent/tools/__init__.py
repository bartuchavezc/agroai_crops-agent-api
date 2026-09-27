from .context import ToolDeps, TurnContext
from .farm import farm_manager_tools, farm_read_tools
from .knowledge import alert_tools, memory_tools, report_tools, search_tools, weather_tools


def build_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    tools = [
        *farm_read_tools(deps, ctx),
        *memory_tools(deps, ctx),
        *weather_tools(deps, ctx),
        *alert_tools(deps, ctx),
        *report_tools(deps, ctx),
        *search_tools(deps, ctx),
    ]
    if ctx.actor.is_manager:
        tools += farm_manager_tools(deps, ctx)
    return tools


__all__ = ["ToolDeps", "TurnContext", "build_tools"]
