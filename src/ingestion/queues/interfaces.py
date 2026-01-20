# src/ingestion/queues/interfaces.py
"""
Message queue interface definitions.

This module defines the abstract interface for message queues,
allowing different implementations (Redis, RabbitMQ, Kafka, etc.)
to be swapped without changing the application code.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
import json


class MessagePriority(Enum):
    """Message priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Message:
    """
    Standard message format for the queue system.
    
    Attributes:
        id: Unique message identifier
        type: Message type/category (e.g., "weather_data", "image_upload")
        payload: Message data
        priority: Message priority level
        created_at: Message creation timestamp
        metadata: Additional message metadata (source, region, etc.)
        retry_count: Number of retry attempts
        max_retries: Maximum retry attempts before moving to DLQ
    """
    type: str
    payload: Dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: MessagePriority = MessagePriority.NORMAL
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    max_retries: int = 3
    
    def to_json(self) -> str:
        """Serialize message to JSON string."""
        return json.dumps({
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> "Message":
        """Deserialize message from JSON string."""
        data = json.loads(json_str)
        return cls(
            id=data["id"],
            type=data["type"],
            payload=data["payload"],
            priority=MessagePriority(data["priority"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )
    
    def increment_retry(self) -> "Message":
        """Return a new message with incremented retry count."""
        return Message(
            id=self.id,
            type=self.type,
            payload=self.payload,
            priority=self.priority,
            created_at=self.created_at,
            metadata=self.metadata,
            retry_count=self.retry_count + 1,
            max_retries=self.max_retries,
        )
    
    @property
    def can_retry(self) -> bool:
        """Check if message can be retried."""
        return self.retry_count < self.max_retries


class IMessageQueue(ABC):
    """
    Abstract interface for message queue implementations.
    
    Implementations should handle:
    - Message publishing to queues
    - Message consumption from queues
    - Priority handling
    - Dead letter queue for failed messages
    - Queue health checking
    """
    
    @abstractmethod
    async def publish(self, queue_name: str, message: Message) -> bool:
        """
        Publish a message to a queue.
        
        Args:
            queue_name: Target queue name
            message: Message to publish
            
        Returns:
            True if published successfully
        """
        pass
    
    @abstractmethod
    async def consume(self, queue_name: str, timeout: Optional[float] = None) -> Optional[Message]:
        """
        Consume a single message from a queue.
        
        Args:
            queue_name: Queue to consume from
            timeout: Max wait time in seconds (None for non-blocking)
            
        Returns:
            Message if available, None otherwise
        """
        pass
    
    @abstractmethod
    async def consume_batch(
        self,
        queue_name: str,
        max_messages: int = 10,
        timeout: Optional[float] = None
    ) -> List[Message]:
        """
        Consume multiple messages from a queue.
        
        Args:
            queue_name: Queue to consume from
            max_messages: Maximum number of messages to consume
            timeout: Max wait time in seconds
            
        Returns:
            List of messages
        """
        pass
    
    @abstractmethod
    async def ack(self, queue_name: str, message_id: str) -> bool:
        """
        Acknowledge message processing completion.
        
        Args:
            queue_name: Queue name
            message_id: Message ID to acknowledge
            
        Returns:
            True if acknowledged successfully
        """
        pass
    
    @abstractmethod
    async def nack(self, queue_name: str, message: Message, requeue: bool = True) -> bool:
        """
        Negative acknowledge - message processing failed.
        
        Args:
            queue_name: Queue name
            message: Failed message
            requeue: Whether to requeue the message
            
        Returns:
            True if handled successfully
        """
        pass
    
    @abstractmethod
    async def get_queue_length(self, queue_name: str) -> int:
        """
        Get the number of messages in a queue.
        
        Args:
            queue_name: Queue name
            
        Returns:
            Number of messages in queue
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check queue system health.
        
        Returns:
            Dictionary with health status information
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close queue connections."""
        pass


# Queue names for different message types
class QueueNames:
    """Standard queue names used in the system."""
    WEATHER_DATA = "ingestion.weather"
    IMAGE_UPLOAD = "ingestion.images"
    SENSOR_DATA = "ingestion.sensors"
    ANALYSIS_REQUESTS = "agent.analysis"
    ALERTS = "action.alerts"
    REPORTS = "action.reports"
    DEAD_LETTER = "dlq"
