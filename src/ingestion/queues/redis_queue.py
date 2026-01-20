# src/ingestion/queues/redis_queue.py
"""
Redis-based message queue implementation.

Uses Redis Lists and Sorted Sets for queue functionality with priority support.
"""
import redis.asyncio as redis
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from .interfaces import IMessageQueue, Message, MessagePriority, QueueNames

logger = logging.getLogger(__name__)


class RedisQueue(IMessageQueue):
    """
    Redis implementation of message queue.
    
    Uses:
    - Sorted Sets for priority queues
    - Hash for message storage
    - List for simple FIFO queues
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 1,
        password: Optional[str] = None,
        prefix: str = "agroai:queue:"
    ):
        """
        Initialize Redis queue.
        
        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Redis password (optional)
            prefix: Key prefix for queue names
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.prefix = prefix
        self._client: Optional[redis.Redis] = None
    
    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
            )
        return self._client
    
    def _queue_key(self, queue_name: str) -> str:
        """Get full Redis key for a queue."""
        return f"{self.prefix}{queue_name}"
    
    def _message_key(self, queue_name: str, message_id: str) -> str:
        """Get full Redis key for a message."""
        return f"{self.prefix}{queue_name}:msg:{message_id}"
    
    def _processing_key(self, queue_name: str) -> str:
        """Get Redis key for processing messages."""
        return f"{self.prefix}{queue_name}:processing"
    
    def _calculate_score(self, message: Message) -> float:
        """
        Calculate score for sorted set ordering.
        Higher priority = lower score = processed first.
        Within same priority, earlier messages processed first.
        """
        # Base score from priority (inverted: CRITICAL=0, LOW=3)
        priority_score = 3 - message.priority.value
        # Add timestamp fraction to maintain FIFO within priority
        timestamp_fraction = message.created_at.timestamp() / 1e12
        return priority_score + timestamp_fraction
    
    async def publish(self, queue_name: str, message: Message) -> bool:
        """Publish message to Redis queue."""
        try:
            client = await self._get_client()
            queue_key = self._queue_key(queue_name)
            message_key = self._message_key(queue_name, message.id)
            
            # Store message data
            await client.set(message_key, message.to_json())
            
            # Add to sorted set with priority score
            score = self._calculate_score(message)
            await client.zadd(queue_key, {message.id: score})
            
            logger.debug(f"Published message {message.id} to {queue_name} with score {score}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing to {queue_name}: {e}")
            return False
    
    async def consume(self, queue_name: str, timeout: Optional[float] = None) -> Optional[Message]:
        """Consume single message from queue."""
        try:
            client = await self._get_client()
            queue_key = self._queue_key(queue_name)
            processing_key = self._processing_key(queue_name)
            
            # Get message with lowest score (highest priority, oldest)
            if timeout:
                # Blocking pop with timeout
                result = await client.bzpopmin(queue_key, timeout=timeout)
                if not result:
                    return None
                _, message_id, _ = result
            else:
                # Non-blocking
                result = await client.zpopmin(queue_key)
                if not result:
                    return None
                message_id, _ = result[0]
            
            # Get message data
            message_key = self._message_key(queue_name, message_id)
            message_data = await client.get(message_key)
            
            if not message_data:
                logger.warning(f"Message {message_id} not found in storage")
                return None
            
            message = Message.from_json(message_data)
            
            # Move to processing set
            await client.sadd(processing_key, message_id)
            
            logger.debug(f"Consumed message {message_id} from {queue_name}")
            return message
            
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
            client = await self._get_client()
            queue_key = self._queue_key(queue_name)
            processing_key = self._processing_key(queue_name)
            
            # Get multiple messages
            results = await client.zpopmin(queue_key, count=max_messages)
            
            for message_id, _ in results:
                message_key = self._message_key(queue_name, message_id)
                message_data = await client.get(message_key)
                
                if message_data:
                    message = Message.from_json(message_data)
                    messages.append(message)
                    await client.sadd(processing_key, message_id)
            
            logger.debug(f"Consumed {len(messages)} messages from {queue_name}")
            return messages
            
        except Exception as e:
            logger.error(f"Error consuming batch from {queue_name}: {e}")
            return messages
    
    async def ack(self, queue_name: str, message_id: str) -> bool:
        """Acknowledge message - remove from processing and storage."""
        try:
            client = await self._get_client()
            processing_key = self._processing_key(queue_name)
            message_key = self._message_key(queue_name, message_id)
            
            # Remove from processing set and delete message
            await client.srem(processing_key, message_id)
            await client.delete(message_key)
            
            logger.debug(f"Acknowledged message {message_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error acknowledging {message_id}: {e}")
            return False
    
    async def nack(self, queue_name: str, message: Message, requeue: bool = True) -> bool:
        """Handle failed message - requeue or send to DLQ."""
        try:
            client = await self._get_client()
            processing_key = self._processing_key(queue_name)
            
            # Remove from processing
            await client.srem(processing_key, message.id)
            
            if requeue and message.can_retry:
                # Increment retry and requeue
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
        try:
            client = await self._get_client()
            queue_key = self._queue_key(queue_name)
            return await client.zcard(queue_key)
        except Exception as e:
            logger.error(f"Error getting queue length for {queue_name}: {e}")
            return 0
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Redis connection health."""
        try:
            client = await self._get_client()
            await client.ping()
            
            # Get queue lengths
            queue_lengths = {}
            for queue_name in [QueueNames.WEATHER_DATA, QueueNames.IMAGE_UPLOAD, QueueNames.DEAD_LETTER]:
                queue_lengths[queue_name] = await self.get_queue_length(queue_name)
            
            return {
                "status": "healthy",
                "backend": "redis",
                "host": self.host,
                "port": self.port,
                "queue_lengths": queue_lengths,
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "redis",
                "error": str(e),
            }
    
    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis queue connection closed")
