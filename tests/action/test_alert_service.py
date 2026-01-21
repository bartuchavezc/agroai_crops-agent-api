# tests/action/test_alert_service.py
"""
Tests for AlertService logic.
"""
import pytest
from datetime import datetime

from src.action.alerts.alert_service import AlertService, Alert


@pytest.fixture
def alert_service():
    """Create a fresh AlertService instance."""
    return AlertService()


class TestAlertService:
    """Tests for AlertService."""

    @pytest.mark.asyncio
    async def test_create_alert_sets_correct_fields(self, alert_service):
        """Verify alert creation populates all expected fields."""
        alert = await alert_service.create_alert(
            title="Test Alert",
            message="This is a test message",
            severity="high",
            type="pest",
            region="AR",
            field_id="field-123",
            metadata={"crop": "soja"},
        )

        assert alert.title == "Test Alert"
        assert alert.message == "This is a test message"
        assert alert.severity == "high"
        assert alert.type == "pest"
        assert alert.region == "AR"
        assert alert.field_id == "field-123"
        assert alert.metadata == {"crop": "soja"}
        assert alert.acknowledged is False
        assert alert.id is not None
        assert isinstance(alert.created_at, datetime)

    @pytest.mark.asyncio
    async def test_list_alerts_filters_by_severity(self, alert_service):
        """Test that list_alerts correctly filters by severity."""
        # Create alerts with different severities
        await alert_service.create_alert(title="Low", message="m", severity="low")
        await alert_service.create_alert(title="High1", message="m", severity="high")
        await alert_service.create_alert(title="High2", message="m", severity="high")
        await alert_service.create_alert(title="Critical", message="m", severity="critical")

        high_alerts = await alert_service.list_alerts(severity="high")
        
        assert len(high_alerts) == 2
        assert all(a.severity == "high" for a in high_alerts)

    @pytest.mark.asyncio
    async def test_acknowledge_alert_updates_status(self, alert_service):
        """Test that acknowledging an alert updates its status."""
        alert = await alert_service.create_alert(
            title="To Acknowledge",
            message="Will be acknowledged",
        )

        assert alert.acknowledged is False
        assert alert.acknowledged_at is None

        updated = await alert_service.acknowledge_alert(alert.id)

        assert updated is not None
        assert updated.acknowledged is True
        assert updated.acknowledged_at is not None
        assert isinstance(updated.acknowledged_at, datetime)

    @pytest.mark.asyncio
    async def test_get_active_alerts_excludes_acknowledged(self, alert_service):
        """Test that get_active_alerts only returns unacknowledged alerts."""
        alert1 = await alert_service.create_alert(title="Active1", message="m")
        alert2 = await alert_service.create_alert(title="Active2", message="m")
        alert3 = await alert_service.create_alert(title="ToAck", message="m")

        await alert_service.acknowledge_alert(alert3.id)

        active = await alert_service.get_active_alerts()

        assert len(active) == 2
        active_ids = {a.id for a in active}
        assert alert1.id in active_ids
        assert alert2.id in active_ids
        assert alert3.id not in active_ids

    @pytest.mark.asyncio
    async def test_delete_alert_removes_from_storage(self, alert_service):
        """Test that deleting an alert removes it from storage."""
        alert = await alert_service.create_alert(title="ToDelete", message="m")
        
        assert await alert_service.get_alert(alert.id) is not None
        
        result = await alert_service.delete_alert(alert.id)
        
        assert result is True
        assert await alert_service.get_alert(alert.id) is None


class TestAlert:
    """Tests for Alert dataclass."""

    def test_to_dict_serializes_all_fields(self):
        """Test that to_dict includes all expected fields."""
        alert = Alert(
            id="alert-1",
            title="Test",
            message="Message",
            severity="medium",
            type="weather",
            region="MX",
        )

        data = alert.to_dict()

        assert data["id"] == "alert-1"
        assert data["title"] == "Test"
        assert data["message"] == "Message"
        assert data["severity"] == "medium"
        assert data["type"] == "weather"
        assert data["region"] == "MX"
        assert "created_at" in data
        assert data["acknowledged"] is False
