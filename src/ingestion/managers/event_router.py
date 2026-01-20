# src/ingestion/managers/event_router.py
"""
Event router for directing incoming messages to appropriate handlers.

This is the central orchestrator that takes messages from queues
and routes them to the appropriate manager for processing.
"""
import asyncio
import logging
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime

from ..queues.interfaces import IMessageQueue, Message, QueueNames

logger = logging.getLogger(__name__)


class EventRouter:
    """
    Routes events from queues to registered handlers.
    
    Supports:
    - Handler registration by message type
    - Concurrent message processing
    - Error handling with retry/DLQ support
    - Graceful shutdown
    """
    
    def __init__(self, queue: IMessageQueue, max_concurrent: int = 10):
        """
        Initialize event router.
        
        Args:
            queue: Message queue implementation
            max_concurrent: Maximum concurrent message handlers
        """
        self.queue = queue
        self.max_concurrent = max_concurrent
        self._handlers: Dict[str, Callable] = {}
        self._running = False
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._tasks: List[asyncio.Task] = []
    
    def register_handler(self, message_type: str, handler: Callable) -> None:
        """
        Register a handler for a message type.
        
        Args:
            message_type: Message type to handle
            handler: Async function to process messages
        """
        self._handlers[message_type] = handler
        logger.info(f"Registered handler for message type: {message_type}")
    
    async def start(self, queues: List[str]) -> None:
        """
        Start processing messages from specified queues.
        
        Args:
            queues: List of queue names to consume from
        """
        if self._running:
            logger.warning("Event router already running")
            return
        
        self._running = True
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        
        logger.info(f"Starting event router for queues: {queues}")
        
        # Create consumer tasks for each queue
        for queue_name in queues:
            task = asyncio.create_task(self._consume_loop(queue_name))
            self._tasks.append(task)
    
    async def stop(self) -> None:
        """Stop processing and wait for current tasks to complete."""
        logger.info("Stopping event router...")
        self._running = False
        
        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        
        logger.info("Event router stopped")
    
    async def _consume_loop(self, queue_name: str) -> None:
        """Main consumption loop for a queue."""
        while self._running:
            try:
                # Get message with timeout
                message = await self.queue.consume(queue_name, timeout=1.0)
                
                if message:
                    # Process with concurrency limit
                    await self._semaphore.acquire()
                    asyncio.create_task(self._process_message(queue_name, message))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in consume loop for {queue_name}: {e}")
                await asyncio.sleep(1)  # Back off on error
    
    async def _process_message(self, queue_name: str, message: Message) -> None:
        """Process a single message."""
        try:
            handler = self._handlers.get(message.type)
            
            if not handler:
                logger.warning(f"No handler for message type: {message.type}")
                await self.queue.nack(queue_name, message, requeue=False)
                return
            
            # Execute handler
            start_time = datetime.utcnow()
            await handler(message)
            
            # Acknowledge success
            await self.queue.ack(queue_name, message.id)
            
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.debug(f"Processed message {message.id} in {duration:.3f}s")
            
        except Exception as e:
            logger.error(f"Error processing message {message.id}: {e}")
            # Requeue for retry
            await self.queue.nack(queue_name, message, requeue=True)
            
        finally:
            self._semaphore.release()
    
    async def process_single(self, message: Message) -> Any:
        """
        Process a single message directly (without queue).
        Useful for synchronous API calls.
        
        Args:
            message: Message to process
            
        Returns:
            Handler result
            
        Raises:
            ValueError: If no handler registered for message type
        """
        handler = self._handlers.get(message.type)
        
        if not handler:
            raise ValueError(f"No handler for message type: {message.type}")
        
        return await handler(message)


# Message types used in the system
class MessageTypes:
    """Standard message types."""
    WEATHER_FETCH = "weather.fetch"
    WEATHER_UPDATE = "weather.update"
    IMAGE_UPLOADED = "image.uploaded"
    IMAGE_ANALYZE = "image.analyze"
    SENSOR_DATA = "sensor.data"
    ALERT_TRIGGER = "alert.trigger"
