"""
Chat API route for FastAPI.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from dependency_injector.wiring import inject, Provide
import logging

# from src.app.chat.service.chat_service import ChatService # Old import
from src.app.agent.service.agent_service import AgentService # New import
from src.app.container import Container

router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
)

logger = logging.getLogger(__name__)

class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to send to the chat LLM.", min_length=1)

class ChatResponse(BaseModel):
    response: str

class ClearMemoryResponse(BaseModel):
    message: str

@router.post("", response_model=ChatResponse, summary="Send Message to Agent", description="Endpoint to interact with the agent.")
@inject
async def chat_endpoint(
    chat_request: ChatRequest,
    # Updated to use AgentService
    agent_service: AgentService = Depends(Provide[Container.agent.agent_service]) 
):
    """Endpoint to interact with the chat LLM (now an Agent).""" # Updated docstring
    try:
        # Updated to call agent_service.get_agent_response
        response_message = await agent_service.get_agent_response(chat_request.message)
        return ChatResponse(response=response_message)
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        # This will be caught as a 500 error by FastAPI's default handler
        # or a custom one like CropAnalysisError if it inherits from it and is raised from the service
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chat response: {str(e)}"
        )

@router.delete("/memory", response_model=ClearMemoryResponse, summary="Clear Conversation Memory", description="Clears the agent's conversation memory.")
@inject
async def clear_memory_endpoint(
    agent_service: AgentService = Depends(Provide[Container.agent.agent_service])
):
    """Endpoint to clear the agent's conversation memory."""
    try:
        agent_service.clear_conversation_memory()
        return ClearMemoryResponse(message="Conversation memory cleared successfully.")
    except Exception as e:
        logger.error(f"Error clearing memory: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear memory: {str(e)}"
        )