# src/agent/reasoning/llm_service.py
"""
LLM service for text generation.
"""
import logging
from typing import Any, Dict, List, Optional
import ollama

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service for LLM text generation using Ollama.
    
    Provides:
    - Text generation with system prompts
    - Conversation history support
    - Streaming (optional)
    - Health checking
    """
    
    def __init__(
        self,
        model_name: str = "gemma:2b",
        ollama_endpoint: str = "http://localhost:11434",
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ):
        """
        Initialize LLM service.
        
        Args:
            model_name: Ollama model name
            ollama_endpoint: Ollama API endpoint
            max_tokens: Maximum tokens to generate
            temperature: Generation temperature
        """
        self.model_name = model_name
        self.ollama_endpoint = ollama_endpoint
        self.max_tokens = max_tokens
        self.temperature = temperature
        
        # Configure Ollama client
        self._client = ollama.AsyncClient(host=ollama_endpoint)
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Generate text response.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            history: Optional conversation history
            
        Returns:
            Generated text
        """
        try:
            # Build messages
            messages = []
            
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            # Add history if provided
            if history:
                messages.extend(history)
            
            # Add current prompt
            messages.append({
                "role": "user",
                "content": prompt
            })
            
            # Generate response
            response = await self._client.chat(
                model=self.model_name,
                messages=messages,
                options={
                    "num_predict": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            return response["message"]["content"]
            
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            raise
    
    async def generate_simple(self, prompt: str) -> str:
        """
        Simple text generation without history.
        
        Args:
            prompt: Input prompt
            
        Returns:
            Generated text
        """
        try:
            response = await self._client.generate(
                model=self.model_name,
                prompt=prompt,
                options={
                    "num_predict": self.max_tokens,
                    "temperature": self.temperature,
                }
            )
            
            return response["response"]
            
        except Exception as e:
            logger.error(f"LLM generation error: {e}")
            raise
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Check LLM service health.
        
        Returns:
            Health status dictionary
        """
        try:
            # Try to list models
            models = await self._client.list()
            
            model_names = [m["name"] for m in models.get("models", [])]
            model_available = any(self.model_name in name for name in model_names)
            
            return {
                "status": "healthy" if model_available else "degraded",
                "model": self.model_name,
                "model_available": model_available,
                "available_models": model_names[:5],  # Limit for brevity
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "model": self.model_name,
                "error": str(e),
            }
