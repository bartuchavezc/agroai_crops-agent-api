# tests/ingestion/test_message.py
"""
Tests for Message class serialization and retry logic.
"""
import pytest
from datetime import datetime

from src.ingestion.queues.interfaces import Message, MessagePriority


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_to_json_roundtrip(self):
        """Message should serialize to JSON and deserialize back correctly."""
        original = Message(
            id="test-123",
            type="weather.data",
            payload={"temperature": 25.5, "humidity": 60},
            priority=MessagePriority.HIGH,
            metadata={"source": "sensor-1", "region": "AR"},
            retry_count=1,
            max_retries=5,
        )
        
        json_str = original.to_json()
        restored = Message.from_json(json_str)
        
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.payload == original.payload
        assert restored.priority == original.priority
        assert restored.metadata == original.metadata
        assert restored.retry_count == original.retry_count
        assert restored.max_retries == original.max_retries

    def test_message_to_json_includes_all_fields(self):
        """JSON output should include all message fields."""
        msg = Message(
            type="test",
            payload={"key": "value"},
        )
        
        json_str = msg.to_json()
        
        assert '"id"' in json_str
        assert '"type"' in json_str
        assert '"payload"' in json_str
        assert '"priority"' in json_str
        assert '"created_at"' in json_str
        assert '"metadata"' in json_str
        assert '"retry_count"' in json_str
        assert '"max_retries"' in json_str

    def test_can_retry_true_when_under_max(self):
        """can_retry should be True when retry_count < max_retries."""
        msg = Message(
            type="test",
            payload={},
            retry_count=0,
            max_retries=3,
        )
        
        assert msg.can_retry is True
        
        # After 2 retries, still can retry
        msg2 = Message(type="test", payload={}, retry_count=2, max_retries=3)
        assert msg2.can_retry is True

    def test_can_retry_false_after_max_retries(self):
        """can_retry should be False when retry_count >= max_retries."""
        msg = Message(
            type="test",
            payload={},
            retry_count=3,
            max_retries=3,
        )
        
        assert msg.can_retry is False

    def test_increment_retry_returns_new_message(self):
        """increment_retry should return a new Message with incremented count."""
        original = Message(
            id="msg-1",
            type="test",
            payload={"data": 123},
            retry_count=0,
        )
        
        incremented = original.increment_retry()
        
        # Original unchanged
        assert original.retry_count == 0
        
        # New message has incremented count
        assert incremented.retry_count == 1
        assert incremented.id == original.id
        assert incremented.type == original.type
        assert incremented.payload == original.payload

    def test_default_priority_is_normal(self):
        """Default priority should be NORMAL."""
        msg = Message(type="test", payload={})
        
        assert msg.priority == MessagePriority.NORMAL

    def test_default_max_retries_is_3(self):
        """Default max_retries should be 3."""
        msg = Message(type="test", payload={})
        
        assert msg.max_retries == 3

    def test_id_is_generated_if_not_provided(self):
        """Message ID should be auto-generated if not provided."""
        msg1 = Message(type="test", payload={})
        msg2 = Message(type="test", payload={})
        
        assert msg1.id is not None
        assert msg2.id is not None
        assert msg1.id != msg2.id  # UUIDs should be unique

    def test_created_at_is_set_automatically(self):
        """created_at should be set to current time if not provided."""
        before = datetime.utcnow()
        msg = Message(type="test", payload={})
        after = datetime.utcnow()
        
        assert before <= msg.created_at <= after


class TestMessagePriority:
    """Tests for MessagePriority enum."""

    def test_priority_values_are_ordered(self):
        """Priority values should be ordered LOW < NORMAL < HIGH < CRITICAL."""
        assert MessagePriority.LOW.value < MessagePriority.NORMAL.value
        assert MessagePriority.NORMAL.value < MessagePriority.HIGH.value
        assert MessagePriority.HIGH.value < MessagePriority.CRITICAL.value

    def test_priority_can_be_compared_by_value(self):
        """Priorities can be compared numerically."""
        assert MessagePriority.CRITICAL.value == 3
        assert MessagePriority.HIGH.value == 2
        assert MessagePriority.NORMAL.value == 1
        assert MessagePriority.LOW.value == 0
