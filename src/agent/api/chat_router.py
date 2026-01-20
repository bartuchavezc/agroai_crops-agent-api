# src/agent/api/chat_router.py
"""
Chat API route for agent interactions.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from dependency_injector.wiring import inject, Provide
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    """Request schema for chat endpoint."""
    message: str = Field(
        ...,
        description="User message to send to the agent.",
        min_length=1,
        max_length=4000,
    )
    context: dict = Field(
        default_factory=dict,
        description="Optional context for the conversation (region, user preferences, etc.)"
    )


class ChatResponse(BaseModel):
    """Response schema for chat endpoint."""
    response: str
    sources: list = Field(default_factory=list, description="Referenced sources")
    metadata: dict = Field(default_factory=dict, description="Response metadata")


class ClearMemoryResponse(BaseModel):
    """Response schema for memory clear endpoint."""
    message: str


@router.post("", response_model=ChatResponse, summary="Send Message to Agent")
@inject
async def chat_endpoint(
    chat_request: ChatRequest,
    agent_service = Depends(Provide["agent.agent_service"]),
):
    """
    Send a message to the agricultural agent and receive a response.
    
    The agent can:
    - Answer general agricultural questions
    - Search technical documentation
    - Provide crop-specific recommendations
    - Access user's report history
    """
    try:
        result = await agent_service.get_agent_response(
            user_message=chat_request.message,
            context=chat_request.context,
        )
        
        return ChatResponse(
            response=result.get("response", ""),
            sources=result.get("sources", []),
            metadata=result.get("metadata", {}),
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chat response: {str(e)}"
        )


@router.delete("/memory", response_model=ClearMemoryResponse, summary="Clear Conversation Memory")
@inject
async def clear_memory_endpoint(
    agent_service = Depends(Provide["agent.agent_service"]),
):
    """
    Clear the agent's conversation memory for the current session.
    """
    try:
        agent_service.clear_conversation_memory()
        return ClearMemoryResponse(message="Conversation memory cleared successfully.")
    except Exception as e:
        logger.error(f"Error clearing memory: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear memory: {str(e)}"
        )


@router.get("/health", summary="Check Agent Health")
@inject
async def agent_health(
    agent_service = Depends(Provide["agent.agent_service"]),
):
    """
    Check the health of the agent and its dependencies.
    """
    try:
        health = await agent_service.health_check()
        return health
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
