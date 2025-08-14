from ..infrastructure.agent_repository_interface import IAgentRepository

class AgentService:
    """Service for handling agent interactions."""
    def __init__(self, agent_repository: IAgentRepository, system_prompt: str):
        self.agent_repository = agent_repository
        self.system_prompt = system_prompt # This will be loaded from config

    async def get_agent_response(self, user_message: str) -> str:
        """Generates a response to a user's message using the Langchain agent."""
        # The system prompt for the repository is already set at initialization
        # from its own config. The service doesn't need to pass it again unless
        # there's a specific reason to override it per request, which is not the case here.
        return await self.agent_repository.send_message(user_message)
        
    def clear_conversation_memory(self):
        """Clears the conversation memory."""
        self.agent_repository.clear_memory() 