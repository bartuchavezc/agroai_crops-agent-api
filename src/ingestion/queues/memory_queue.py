# src/ingestion/queues/memory_queue.py
"""
In-memory message queue implementation for development and testing.

WARNING: This implementation is NOT suitable for production use.
Messages are lost on restart and there's no persistence.
"""
import asyncio
import heapq
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .interfaces import IMessageQueue, Message, MessagePriority, QueueNames

logger = logging.getLogger(__name__)


class MemoryQueue(IMessageQueue):
    """
    In-memory implementation of message queue for dev/testing.
    
    Uses:
    - heapq for priority queue functionality
    - dict for message storage
    - set for tracking processing messages
    """
    
    def __init__(self):
        """Initialize in-memory queue."""
        self._queues: Dict[str, List[Tuple[float, str]]] = {}  # queue_name -> heap
        self._messages: Dict[str, Message] = {}  # message_id -> Message
        self._processing: Dict[str, set] = {}  # queue_name -> set of message_ids
        self._locks: Dict[str, asyncio.Lock] = {}
        logger.warning("Using in-memory queue - NOT suitable for production!")
    
    def _get_lock(self, queue_name: str) -> asyncio.Lock:
        """Get or create lock for a queue."""
        if queue_name not in self._locks:
            self._locks[queue_name] = asyncio.Lock()
        return self._locks[queue_name]
    
    def _ensure_queue(self, queue_name: str) -> None:
        """Ensure queue structures exist."""
        if queue_name not in self._queues:
            self._queues[queue_name] = []
            self._processing[queue_name] = set()
    
    def _calculate_score(self, message: Message) -> float:
        """Calculate priority score for heap ordering."""
        priority_score = 3 - message.priority.value
        timestamp_fraction = message.created_at.timestamp() / 1e12
        return priority_score + timestamp_fraction
    
    async def publish(self, queue_name: str, message: Message) -> bool:
        """Publish message to in-memory queue."""
        try:
            async with self._get_lock(queue_name):
                self._ensure_queue(queue_name)
                
                # Store message
                self._messages[message.id] = message
                
                # Add to heap
                score = self._calculate_score(message)
                heapq.heappush(self._queues[queue_name], (score, message.id))
                
                logger.debug(f"Published message {message.id} to {queue_name}")
                return True
                
        except Exception as e:
            logger.error(f"Error publishing to {queue_name}: {e}")
            return False
    
    async def consume(self, queue_name: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Consume single message from queue."""
        try:
            start_time = datetime.utcnow()
            
            while True:
                async with self._get_lock(queue_name):
                    self._ensure_queue(queue_name)
                    
                    if self._queues[queue_name]:
                        _, message_id = heapq.heappop(self._queues[queue_name])
                        message = self._messages.get(message_id)
                        
                        if message:
                            self._processing[queue_name].add(message_id)
                            logger.debug(f"Consumed message {message_id} from {queue_name}")
                            return message
                
                # Check timeout
                if timeout is None:
                    return None
                
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed >= timeout:
                    return None
                
                # Wait a bit before retry
                await asyncio.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error consuming from {queue_name}: {e}")
            return None
    
    async def consume_batch(
        self,
        queue_name: str,
        max_messages: int = 10,
        timeout: Optional[float] = None
    ) -> List[Message]:
        """Consume multiple messages from queue."""
        messages = []
        
        try:
            async with self._get_lock(queue_name):
                self._ensure_queue(queue_name)
                
                for _ in range(max_messages):
                    if not self._queues[queue_name]:
                        break
                    
                    _, message_id = heapq.heappop(self._queues[queue_name])
                    message = self._messages.get(message_id)
                    
                    if message:
                        self._processing[queue_name].add(message_id)
                        messages.append(message)
                
                logger.debug(f"Consumed {len(messages)} messages from {queue_name}")
                return messages
                
        except Exception as e:
            logger.error(f"Error consuming batch from {queue_name}: {e}")
            return messages
    
    async def ack(self, queue_name: str, message_id: str) -> bool:
        """Acknowledge message - remove from processing and storage."""
        try:
            async with self._get_lock(queue_name):
                self._ensure_queue(queue_name)
                
                self._processing[queue_name].discard(message_id)
                self._messages.pop(message_id, None)
                
                logger.debug(f"Acknowledged message {message_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error acknowledging {message_id}: {e}")
            return False
    
    async def nack(self, queue_name: str, message: Message, requeue: bool = True) -> bool:
        """Handle failed message."""
        try:
            async with self._get_lock(queue_name):
                self._ensure_queue(queue_name)
                self._processing[queue_name].discard(message.id)
            
            if requeue and message.can_retry:
                retry_message = message.increment_retry()
                return await self.publish(queue_name, retry_message)
            else:
                # Send to dead letter queue
                dlq_message = Message(
                    id=message.id,
                    type=message.type,
                    payload=message.payload,
                    priority=MessagePriority.LOW,
                    metadata={
                        **message.metadata,
                        "original_queue": queue_name,
                        "final_retry_count": message.retry_count,
                        "failed_at": datetime.utcnow().isoformat(),
                    }
                )
                return await self.publish(QueueNames.DEAD_LETTER, dlq_message)
            
        except Exception as e:
            logger.error(f"Error nacking {message.id}: {e}")
            return False
    
    async def get_queue_length(self, queue_name: str) -> int:
        """Get number of messages in queue."""
        async with self._get_lock(queue_name):
            self._ensure_queue(queue_name)
            return len(self._queues[queue_name])
    
    async def health_check(self) -> Dict[str, Any]:
        """Return health status."""
        queue_lengths = {}
        for queue_name in self._queues:
            queue_lengths[queue_name] = len(self._queues[queue_name])
        
        return {
            "status": "healthy",
            "backend": "memory",
            "warning": "In-memory queue - not suitable for production",
            "queue_lengths": queue_lengths,
        }
    
    async def close(self) -> None:
        """Clear all data."""
        self._queues.clear()
        self._messages.clear()
        self._processing.clear()
        logger.info("In-memory queue cleared")
