from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

NotificationType = Literal["report_diagnosis", "report_periodic", "report_soil", "event", "reminder"]
EntityType = Literal["report", "event", "reminder"]


class Notification(BaseModel):
    id: UUID
    type: NotificationType
    title: str
    message: str
    field_id: Optional[UUID] = None
    entity_type: EntityType
    entity_id: UUID
    read: bool = False
    read_at: Optional[datetime] = None
    created_at: datetime

    @classmethod
    def from_model(cls, m) -> "Notification":
        return cls(
            id=m.id,
            type=m.type,
            title=m.title,
            message=m.message,
            field_id=m.field_id,
            entity_type=m.entity_type,
            entity_id=m.entity_id,
            read=m.read_at is not None,
            read_at=m.read_at,
            created_at=m.created_at,
        )


class UnreadCount(BaseModel):
    count: int = Field(ge=0)
