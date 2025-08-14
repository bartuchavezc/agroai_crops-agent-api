from dependency_injector import containers, providers
from langchain.tools import Tool # For type hinting

from .service.agent_service import AgentService
from .infrastructure.langchain_agent_repository import LangchainAgentRepository
from .infrastructure.agent_repository_interface import IAgentRepository
from .tools import create_get_report_history_tool # Import the tool factory
from src.app.reports.service.reports_service import ReportsService # Dependency


class AgentContainer(containers.DeclarativeContainer):
    """Container for the agent module's dependencies."""

    # The main application config will be injected here by the application container
    # For now, we assume it's a dict. In a real scenario, you'd likely have a Pydantic model for the entire app config.
    app_config = providers.Configuration(name="app_config")

    # Declare a dependency on ReportsService.
    # This will be injected by a higher-level application container.
    reports_service = providers.Dependency(instance_of=ReportsService)

    # Provider for the list of tools
    tools_provider = providers.List(
        providers.Factory(
            create_get_report_history_tool,
            reports_service=reports_service
        )
        # Add other tool factories here if you have more tools
    )

    agent_repository = providers.Singleton[
        IAgentRepository, LangchainAgentRepository
    ](
        LangchainAgentRepository,
        # Pass the agent_llm sub-dictionary from the main app_config
        agent_llm_config=app_config.agent_llm,
        tools=tools_provider  # Inject the list of tools
    )

    agent_service = providers.Factory[
        AgentService
    ](
        AgentService,
        agent_repository=agent_repository,
        # Get system_prompt from the agent_llm sub-dictionary
        system_prompt=app_config.agent_llm.system_prompt
    ) 