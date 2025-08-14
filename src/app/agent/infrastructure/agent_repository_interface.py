from abc import ABC, abstractmethod

class IAgentRepository(ABC):
    """Interface for agent repositories."""

    @abstractmethod
    async def send_message(self, user_message: str) -> str:
        """Sends a message to the agent and returns the response."""
        pass
        
    @abstractmethod
    def clear_memory(self):
        """Clears the conversation memory."""
        pass 