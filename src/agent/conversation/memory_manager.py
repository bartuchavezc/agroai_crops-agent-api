# src/agent/conversation/memory_manager.py
"""
Conversation memory management.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConversationTurn:
    """Single turn in a conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MemoryManager:
    """
    Manages conversation memory with configurable window size.
    
    Features:
    - Rolling window of recent turns
    - Context extraction for search queries
    - Summary generation for long conversations
    """
    
    def __init__(self, max_turns: int = 10, max_tokens_estimate: int = 2000):
        """
        Initialize memory manager.
        
        Args:
            max_turns: Maximum number of conversation turns to keep
            max_tokens_estimate: Estimated max tokens for context (for pruning)
        """
        self.max_turns = max_turns
        self.max_tokens_estimate = max_tokens_estimate
        self._history: List[ConversationTurn] = []
        self._context: Dict[str, Any] = {}
    
    def add_turn(self, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        """
        Add a conversation turn.
        
        Args:
            role: "user" or "assistant"
            content: Message content
            metadata: Optional metadata (sources, confidence, etc.)
        """
        turn = ConversationTurn(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self._history.append(turn)
        
        # Prune if exceeds max turns
        if len(self._history) > self.max_turns:
            self._history = self._history[-self.max_turns:]
        
        logger.debug(f"Added {role} turn, history size: {len(self._history)}")
    
    def add_user_message(self, content: str) -> None:
        """Add a user message."""
        self.add_turn("user", content)
    
    def add_assistant_message(self, content: str, metadata: Optional[Dict] = None) -> None:
        """Add an assistant message."""
        self.add_turn("assistant", content, metadata)
    
    def get_history(self) -> List[ConversationTurn]:
        """Get full conversation history."""
        return self._history.copy()
    
    def get_history_as_messages(self) -> List[Dict[str, str]]:
        """Get history formatted as message dicts for LLM."""
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self._history
        ]
    
    def get_history_as_text(self) -> str:
        """Get history formatted as text block."""
        lines = []
        for turn in self._history:
            prefix = "Usuario" if turn.role == "user" else "Asistente"
            lines.append(f"{prefix}: {turn.content}")
        return "\n".join(lines)
    
    def get_recent_context(self, n_turns: int = 3) -> str:
        """
        Get recent conversation context for search queries.
        
        Args:
            n_turns: Number of recent turns to include
            
        Returns:
            Concatenated recent messages
        """
        recent = self._history[-n_turns:] if self._history else []
        return " ".join(turn.content for turn in recent)
    
    def set_context(self, key: str, value: Any) -> None:
        """
        Set conversation context variable.
        
        Args:
            key: Context key
            value: Context value
        """
        self._context[key] = value
    
    def get_context(self, key: str, default: Any = None) -> Any:
        """
        Get conversation context variable.
        
        Args:
            key: Context key
            default: Default value if not found
            
        Returns:
            Context value or default
        """
        return self._context.get(key, default)
    
    def get_all_context(self) -> Dict[str, Any]:
        """Get all context variables."""
        return self._context.copy()
    
    def clear(self) -> None:
        """Clear all memory."""
        self._history.clear()
        self._context.clear()
        logger.info("Conversation memory cleared")
    
    def clear_history(self) -> None:
        """Clear only conversation history, keep context."""
        self._history.clear()
    
    @property
    def turn_count(self) -> int:
        """Get number of turns in history."""
        return len(self._history)
    
    @property
    def is_empty(self) -> bool:
        """Check if history is empty."""
        return len(self._history) == 0
    
    def extract_topics(self) -> List[str]:
        """
        Extract main topics from conversation history.
        Simple keyword extraction for search enhancement.
        
        Returns:
            List of topic keywords
        """
        # Simple implementation - could be enhanced with NLP
        all_text = " ".join(turn.content for turn in self._history if turn.role == "user")
        
        # Basic keyword extraction (could use TF-IDF or entity extraction)
        words = all_text.lower().split()
        # Filter common words, keep longer meaningful words
        topics = [w for w in words if len(w) > 4 and w.isalpha()]
        
        # Return unique topics
        return list(set(topics))[:10]
