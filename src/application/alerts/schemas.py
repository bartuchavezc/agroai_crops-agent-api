from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]


class AlertCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    message: str = Field(min_length=1)
    severity: Severity = "medium"
    type: str = Field(default="system", max_length=30)
    field_id: Optional[UUID] = None
    recommendations: list[str] = Field(default_factory=list)


class Alert(BaseModel):
    id: UUID
    title: str
    message: str
    severity: Severity
    type: str
    field_id: Optional[UUID] = None
    rule_id: Optional[str] = None
    recommendations: list[str] = Field(default_factory=list)
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[UUID] = None

    @classmethod
    def from_model(cls, m) -> "Alert":
        return cls(
            id=m.id,
            title=m.title,
            message=m.message,
            severity=m.severity,
            type=m.alert_type,
            field_id=m.field_id,
            rule_id=m.rule_id,
            recommendations=m.recommendations or [],
            source=m.source,
            metadata=m.extra or {},
            valid_from=m.valid_from,
            valid_to=m.valid_to,
            created_at=m.created_at,
            acknowledged=m.acknowledged_at is not None,
            acknowledged_at=m.acknowledged_at,
            acknowledged_by=m.acknowledged_by,
        )
