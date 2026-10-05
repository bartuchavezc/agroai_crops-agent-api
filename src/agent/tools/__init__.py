from .context import ToolDeps, TurnContext
from .farm import farm_manager_tools, farm_read_tools
from .inventory import inventory_manager_tools, inventory_read_tools
from .irrigation import irrigation_tools
from .knowledge import alert_tools, memory_tools, report_tools, search_tools, weather_tools
from .management import management_manager_tools, management_read_tools
from .planning import planning_manager_tools, planning_read_tools
from .satellite import satellite_tools
from .soil import soil_tools


def build_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    tools = [
        *farm_read_tools(deps, ctx),
        *memory_tools(deps, ctx),
        *weather_tools(deps, ctx),
        *alert_tools(deps, ctx),
        *report_tools(deps, ctx),
        *search_tools(deps, ctx),
        *irrigation_tools(deps, ctx),
        *inventory_read_tools(deps, ctx),
        *management_read_tools(deps, ctx),
        *planning_read_tools(deps, ctx),
        *satellite_tools(deps, ctx),
        *soil_tools(deps, ctx),
    ]
    if ctx.actor.is_manager:
        tools += farm_manager_tools(deps, ctx)
        tools += inventory_manager_tools(deps, ctx)
        tools += management_manager_tools(deps, ctx)
        tools += planning_manager_tools(deps, ctx)
    return tools


__all__ = ["ToolDeps", "TurnContext", "build_tools"]
