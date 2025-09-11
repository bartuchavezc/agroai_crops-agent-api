from langchain.tools import Tool
from src.app.reports.service.reports_service import ReportsService
# No need for asgiref.sync here anymore

def create_get_report_history_tool(reports_service: ReportsService) -> Tool:
    """Creates a Langchain Tool to get user report history."""

    # The tool's function can be async if the agent executor supports it.
    # Modern Langchain agent executors, especially with FastAPI, often do.
    async def get_report_history_directly_async(tool_input: str | dict = None) -> str:
        """
        Async function called by Langchain.
        The LLM might pass a string or a dict. We need to handle it.
        For now, we'll ignore the LLM's verbose input and use defaults.
        A more robust solution involves Pydantic models for tool inputs.
        """
        # For simplicity, ignore LLM's natural language input for now
        # and call with default parameters.
        user_id_arg = None
        limit_arg = 5

        # Placeholder for more robust input parsing based on 'tool_input'
        # if isinstance(tool_input, dict):
        #     user_id_arg = tool_input.get("user_id")
        #     limit_arg = tool_input.get("limit", 5)
        # elif isinstance(tool_input, str) and tool_input.lower() != 'none':
        #     # Basic attempt to parse if LLM provides something structured, e.g. "user_id=123, limit=3"
        #     # This is fragile and Pydantic args_schema is preferred for real use.
        #     try:
        #         params = dict(item.split("=") for item in tool_input.split(", "))
        #         user_id_arg = params.get("user_id")
        #         limit_arg = int(params.get("limit", 5))
        #     except ValueError:
        #         pass # Keep defaults if parsing fails

        return await reports_service.get_reports_summary_for_agent(user_id=user_id_arg, limit=limit_arg)

    return Tool(
        name="get_report_history",
        func=None, # We will set coroutine for async tool
        coroutine=get_report_history_directly_async, # Use the async function directly
        description="Consulta el historial de reportes de análisis de cultivos del usuario. " \
                    "Puede usarse para obtener un resumen de los reportes recientes. " \
                    "No necesita parámetros explícitos del usuario, usará valores por defecto.",
        # If this still gives issues with input, the next step is Pydantic args_schema for the tool.
    ) 