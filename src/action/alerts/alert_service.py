# src/action/alerts/alert_service.py
"""
Alert service for managing system alerts and notifications.
"""
import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """Alert data class."""
    id: str
    title: str
    message: str
    severity: str  # low, medium, high, critical
    type: str  # weather, pest, disease, nutrient, system
    created_at: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    region: Optional[str] = None
    field_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "type": self.type,
            "created_at": self.created_at.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "region": self.region,
            "field_id": self.field_id,
            "metadata": self.metadata,
        }


class AlertService:
    """
    Service for managing alerts.
    
    Provides:
    - Alert creation and storage
    - Alert querying and filtering
    - Alert acknowledgment
    - Notification dispatching (placeholder)
    """
    
    def __init__(self, queue=None, notification_adapters: Optional[List] = None):
        """
        Initialize alert service.
        
        Args:
            queue: Optional message queue for alert notifications
            notification_adapters: Optional list of notification adapters
        """
        self.queue = queue
        self.notification_adapters = notification_adapters or []
        
        # In-memory storage (should be replaced with DB in production)
        self._alerts: Dict[str, Alert] = {}
    
    async def create_alert(
        self,
        title: str,
        message: str,
        severity: str = "medium",
        type: str = "system",
        region: Optional[str] = None,
        field_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Alert:
        """
        Create a new alert.
        
        Args:
            title: Alert title
            message: Alert message
            severity: Severity level
            type: Alert type
            region: Optional region
            field_id: Optional field ID
            metadata: Optional additional metadata
            
        Returns:
            Created alert
        """
        alert = Alert(
            id=str(uuid.uuid4()),
            title=title,
            message=message,
            severity=severity,
            type=type,
            region=region,
            field_id=field_id,
            metadata=metadata or {},
        )
        
        self._alerts[alert.id] = alert
        logger.info(f"Created alert: {alert.id} - {severity.upper()}: {title}")
        
        # Dispatch notifications
        await self._dispatch_notifications(alert)
        
        return alert
    
    async def _dispatch_notifications(self, alert: Alert) -> None:
        """Dispatch alert to notification adapters."""
        for adapter in self.notification_adapters:
            try:
                await adapter.send(alert)
            except Exception as e:
                logger.error(f"Error dispatching notification: {e}")
        
        # Optionally publish to queue
        if self.queue:
            try:
                from src.ingestion.queues.interfaces import Message, MessagePriority
                
                # Map severity to priority
                priority_map = {
                    "critical": MessagePriority.CRITICAL,
                    "high": MessagePriority.HIGH,
                    "medium": MessagePriority.NORMAL,
                    "low": MessagePriority.LOW,
                }
                
                message = Message(
                    type="alert.created",
                    payload=alert.to_dict(),
                    priority=priority_map.get(alert.severity, MessagePriority.NORMAL),
                )
                
                await self.queue.publish("action.alerts", message)
            except Exception as e:
                logger.error(f"Error publishing alert to queue: {e}")
    
    async def get_alert(self, alert_id: str) -> Optional[Alert]:
        """
        Get an alert by ID.
        
        Args:
            alert_id: Alert ID
            
        Returns:
            Alert if found
        """
        return self._alerts.get(alert_id)
    
    async def list_alerts(
        self,
        acknowledged: Optional[bool] = None,
        severity: Optional[str] = None,
        type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Alert]:
        """
        List alerts with optional filters.
        
        Args:
            acknowledged: Filter by acknowledged status
            severity: Filter by severity
            type: Filter by type
            limit: Maximum results
            
        Returns:
            List of alerts
        """
        alerts = list(self._alerts.values())
        
        # Apply filters
        if acknowledged is not None:
            alerts = [a for a in alerts if a.acknowledged == acknowledged]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if type:
            alerts = [a for a in alerts if a.type == type]
        
        # Sort by creation time (newest first)
        alerts.sort(key=lambda a: a.created_at, reverse=True)
        
        return alerts[:limit]
    
    async def get_active_alerts(self) -> List[Alert]:
        """
        Get all unacknowledged alerts.
        
        Returns:
            List of active alerts
        """
        return await self.list_alerts(acknowledged=False)
    
    async def acknowledge_alert(self, alert_id: str) -> Optional[Alert]:
        """
        Acknowledge an alert.
        
        Args:
            alert_id: Alert ID
            
        Returns:
            Updated alert if found
        """
        alert = self._alerts.get(alert_id)
        if not alert:
            return None
        
        alert.acknowledged = True
        alert.acknowledged_at = datetime.utcnow()
        
        logger.info(f"Acknowledged alert: {alert_id}")
        return alert
    
    async def delete_alert(self, alert_id: str) -> bool:
        """
        Delete an alert.
        
        Args:
            alert_id: Alert ID
            
        Returns:
            True if deleted
        """
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            return True
        return False
