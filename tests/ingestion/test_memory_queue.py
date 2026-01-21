# tests/ingestion/test_memory_queue.py
"""
Tests for MemoryQueue implementation.
"""
import pytest
from datetime import datetime, timedelta

from src.ingestion.queues.memory_queue import MemoryQueue
from src.ingestion.queues.interfaces import Message, MessagePriority, QueueNames


@pytest.fixture
def memory_queue():
    """Create a fresh MemoryQueue instance."""
    return MemoryQueue()


@pytest.fixture
def sample_message():
    """Create a sample message for testing."""
    return Message(
        type="test.event",
        payload={"data": "test_value"},
        priority=MessagePriority.NORMAL,
    )


class TestMemoryQueue:
    """Tests for MemoryQueue pub/sub operations."""

    @pytest.mark.asyncio
    async def test_publish_and_consume_maintains_fifo_within_priority(self, memory_queue):
        """Messages with same priority should be consumed in FIFO order."""
        queue_name = "test.queue"
        base_time = datetime.utcnow()
        
        # Create messages with explicit timestamps to ensure ordering
        msg1 = Message(type="test", payload={"order": 1})
        msg1.created_at = base_time
        
        msg2 = Message(type="test", payload={"order": 2})
        msg2.created_at = base_time + timedelta(milliseconds=10)
        
        msg3 = Message(type="test", payload={"order": 3})
        msg3.created_at = base_time + timedelta(milliseconds=20)
        
        await memory_queue.publish(queue_name, msg1)
        await memory_queue.publish(queue_name, msg2)
        await memory_queue.publish(queue_name, msg3)
        
        # Consume and verify order
        consumed1 = await memory_queue.consume(queue_name)
        consumed2 = await memory_queue.consume(queue_name)
        consumed3 = await memory_queue.consume(queue_name)
        
        assert consumed1.payload["order"] == 1
        assert consumed2.payload["order"] == 2
        assert consumed3.payload["order"] == 3

    @pytest.mark.asyncio
    async def test_priority_ordering_critical_before_normal(self, memory_queue):
        """Critical priority messages should be consumed before normal priority."""
        queue_name = "test.priority"
        
        # Publish normal first, then critical
        normal_msg = Message(
            type="test",
            payload={"priority": "normal"},
            priority=MessagePriority.NORMAL,
        )
        critical_msg = Message(
            type="test",
            payload={"priority": "critical"},
            priority=MessagePriority.CRITICAL,
        )
        
        await memory_queue.publish(queue_name, normal_msg)
        await memory_queue.publish(queue_name, critical_msg)
        
        # Critical should come first despite being published second
        first = await memory_queue.consume(queue_name)
        second = await memory_queue.consume(queue_name)
        
        assert first.payload["priority"] == "critical"
        assert second.payload["priority"] == "normal"

    @pytest.mark.asyncio
    async def test_ack_removes_message_from_storage(self, memory_queue, sample_message):
        """After ack, message should be removed from internal storage."""
        queue_name = "test.ack"
        
        await memory_queue.publish(queue_name, sample_message)
        consumed = await memory_queue.consume(queue_name)
        
        # Message should be in _messages before ack
        assert consumed.id in memory_queue._messages
        
        await memory_queue.ack(queue_name, consumed.id)
        
        # Message should be removed after ack
        assert consumed.id not in memory_queue._messages

    @pytest.mark.asyncio
    async def test_nack_with_requeue_increments_retry(self, memory_queue):
        """Nack with requeue should increment retry count."""
        queue_name = "test.nack"
        
        msg = Message(
            type="test",
            payload={"value": 1},
            max_retries=3,
        )
        
        await memory_queue.publish(queue_name, msg)
        consumed = await memory_queue.consume(queue_name)
        
        assert consumed.retry_count == 0
        
        # Nack with requeue
        await memory_queue.nack(queue_name, consumed, requeue=True)
        
        # Consume again - retry count should be incremented
        requeued = await memory_queue.consume(queue_name)
        
        assert requeued.retry_count == 1
        assert requeued.id == consumed.id

    @pytest.mark.asyncio
    async def test_nack_without_requeue_sends_to_dlq(self, memory_queue):
        """Nack without requeue should send to dead letter queue."""
        queue_name = "test.dlq"
        
        msg = Message(
            type="test",
            payload={"value": 1},
        )
        
        await memory_queue.publish(queue_name, msg)
        consumed = await memory_queue.consume(queue_name)
        
        # Nack without requeue
        await memory_queue.nack(queue_name, consumed, requeue=False)
        
        # Original queue should be empty
        original_length = await memory_queue.get_queue_length(queue_name)
        assert original_length == 0
        
        # DLQ should have the message
        dlq_length = await memory_queue.get_queue_length(QueueNames.DEAD_LETTER)
        assert dlq_length == 1

    @pytest.mark.asyncio
    async def test_consume_batch_respects_max_messages(self, memory_queue):
        """consume_batch should return at most max_messages."""
        queue_name = "test.batch"
        
        # Publish 5 messages
        for i in range(5):
            msg = Message(type="test", payload={"i": i})
            await memory_queue.publish(queue_name, msg)
        
        # Consume batch of 3
        batch = await memory_queue.consume_batch(queue_name, max_messages=3)
        
        assert len(batch) == 3

    @pytest.mark.asyncio
    async def test_get_queue_length_accurate(self, memory_queue):
        """get_queue_length should return correct count."""
        queue_name = "test.length"
        
        assert await memory_queue.get_queue_length(queue_name) == 0
        
        await memory_queue.publish(queue_name, Message(type="t", payload={}))
        await memory_queue.publish(queue_name, Message(type="t", payload={}))
        
        assert await memory_queue.get_queue_length(queue_name) == 2

    @pytest.mark.asyncio
    async def test_health_check_returns_status(self, memory_queue):
        """health_check should return healthy status."""
        health = await memory_queue.health_check()
        
        assert health["status"] == "healthy"
        assert health["backend"] == "memory"

    @pytest.mark.asyncio
    async def test_consume_returns_none_when_empty(self, memory_queue):
        """Consume on empty queue should return None (non-blocking)."""
        result = await memory_queue.consume("empty.queue", timeout=None)
        
        assert result is None
