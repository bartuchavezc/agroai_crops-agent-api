# src/agent/conversation/agent_service.py
"""
Main agent service - orchestrates conversation, search, and reasoning.
"""
import logging
from typing import Any, Dict, List, Optional

from .memory_manager import MemoryManager

logger = logging.getLogger(__name__)


class AgentService:
    """
    Main agent service that orchestrates:
    - Conversation management
    - Two-stage search (summaries → documents)
    - LLM reasoning with context
    - Tool execution
    """
    
    def __init__(
        self,
        llm_service,
        search_service,
        reasoning_service=None,
        tools: Optional[List] = None,
        system_prompt: str = "",
        max_memory_turns: int = 10,
    ):
        """
        Initialize agent service.
        
        Args:
            llm_service: LLM service for text generation
            search_service: Two-stage search service
            reasoning_service: Optional reasoning/diagnosis service
            tools: List of available tools
            system_prompt: System prompt for the agent
            max_memory_turns: Max conversation turns to remember
        """
        self.llm_service = llm_service
        self.search_service = search_service
        self.reasoning_service = reasoning_service
        self.tools = tools or []
        self.system_prompt = system_prompt
        self.memory = MemoryManager(max_turns=max_memory_turns)
    
    async def get_agent_response(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Process user message and generate response.
        
        Args:
            user_message: User's input message
            context: Optional context (region, user preferences, etc.)
            
        Returns:
            Dictionary with response, sources, and metadata
        """
        try:
            # Update context if provided
            if context:
                for key, value in context.items():
                    self.memory.set_context(key, value)
            
            # Add user message to memory
            self.memory.add_user_message(user_message)
            
            # Step 1: Determine if we need to search for information
            search_results = await self._search_if_needed(user_message)
            
            # Step 2: Build context for LLM
            llm_context = self._build_llm_context(user_message, search_results)
            
            # Step 3: Generate response with LLM
            response = await self.llm_service.generate(
                prompt=llm_context["prompt"],
                system_prompt=self.system_prompt,
                history=self.memory.get_history_as_messages(),
            )
            
            # Add assistant response to memory
            self.memory.add_assistant_message(
                response,
                metadata={"sources": llm_context.get("sources", [])}
            )
            
            return {
                "response": response,
                "sources": llm_context.get("sources", []),
                "metadata": {
                    "search_performed": bool(search_results),
                    "documents_found": len(search_results) if search_results else 0,
                    "memory_turns": self.memory.turn_count,
                }
            }
            
        except Exception as e:
            logger.error(f"Error generating agent response: {e}", exc_info=True)
            return {
                "response": "Lo siento, ocurrió un error procesando tu consulta. Por favor, intenta de nuevo.",
                "sources": [],
                "metadata": {"error": str(e)}
            }
    
    async def _search_if_needed(self, user_message: str) -> List[Dict[str, Any]]:
        """
        Determine if search is needed and perform two-stage search.
        
        Args:
            user_message: User's message
            
        Returns:
            List of relevant documents
        """
        if not self.search_service:
            return []
        
        # Simple heuristic: search for questions or specific topics
        search_indicators = [
            "?", "cómo", "qué", "cuál", "cuándo", "dónde", "por qué",
            "plaga", "enfermedad", "tratamiento", "fertilizante",
            "riego", "cultivo", "cosecha", "siembra"
        ]
        
        should_search = any(
            indicator in user_message.lower()
            for indicator in search_indicators
        )
        
        if not should_search:
            return []
        
        try:
            # Get conversation context for better search
            context = self.memory.get_recent_context(n_turns=2)
            region = self.memory.get_context("region")
            
            # Perform two-stage search
            results = await self.search_service.search(
                query=user_message,
                context=context,
                region=region,
                max_results=5,
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []
    
    def _build_llm_context(
        self,
        user_message: str,
        search_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build context for LLM prompt.
        
        Args:
            user_message: User's message
            search_results: Retrieved documents
            
        Returns:
            Dictionary with prompt and sources
        """
        sources = []
        context_parts = []
        
        if search_results:
            context_parts.append("Información relevante encontrada:")
            for i, doc in enumerate(search_results, 1):
                context_parts.append(f"\n[{i}] {doc.get('title', 'Sin título')}")
                context_parts.append(doc.get('content', '')[:500])
                sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "source": doc.get("source"),
                })
            context_parts.append("\n---")
        
        # Add conversation history context
        if not self.memory.is_empty:
            context_parts.append("\nContexto de la conversación:")
            context_parts.append(self.memory.get_history_as_text())
            context_parts.append("\n---")
        
        # Build final prompt
        context_text = "\n".join(context_parts) if context_parts else ""
        prompt = f"{context_text}\n\nUsuario: {user_message}"
        
        return {
            "prompt": prompt,
            "sources": sources,
        }
    
    def clear_conversation_memory(self) -> None:
        """Clear conversation memory."""
        self.memory.clear()
        logger.info("Agent conversation memory cleared")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check agent health and dependencies.
        
        Returns:
            Health status dictionary
        """
        status = {
            "status": "healthy",
            "components": {}
        }
        
        # Check LLM service
        try:
            llm_health = await self.llm_service.health_check()
            status["components"]["llm"] = llm_health
        except Exception as e:
            status["components"]["llm"] = {"status": "unhealthy", "error": str(e)}
            status["status"] = "degraded"
        
        # Check search service
        if self.search_service:
            try:
                search_health = await self.search_service.health_check()
                status["components"]["search"] = search_health
            except Exception as e:
                status["components"]["search"] = {"status": "unhealthy", "error": str(e)}
                status["status"] = "degraded"
        
        return status
