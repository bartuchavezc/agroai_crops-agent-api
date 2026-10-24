from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.application.farm.schemas import EventEvidence, FieldEventRead

FollowUpKind = Literal["pest", "disease", "deficiency", "other"]
FollowUpStatus = Literal["abierto", "resuelto", "descartado"]
Severity = Literal["low", "medium", "high", "critical"]
# How a follow-up looked at one evaluation, compared with the last photo of it.
Evolution = Literal["mejor", "igual", "peor", "no_visible"]


class FollowUpCreate(BaseModel):
    """Open a follow-up: also writes its first bitácora entry ("Se detectó: …"), with the evidence given."""
    field_id: UUID
    zone_id: Optional[UUID] = None
    lot_ids: list[UUID] = Field(default_factory=list, description="The lots affected; none = the zone as a whole")
    title: str = Field(min_length=1, max_length=255, description='"Pulgón en tomate"')
    kind: FollowUpKind = "other"
    severity: Severity = "medium"
    photo_hint: Optional[str] = Field(default=None, max_length=500, description='"envés de las hojas de arriba"')
    notes: Optional[str] = Field(default=None, description="What was seen, for the opening entry")
    evidence: list[EventEvidence] = Field(default_factory=list)
    origin_report_id: Optional[UUID] = Field(default=None, description="The analysis that saw it, if any")


class FollowUpUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    kind: Optional[FollowUpKind] = None
    severity: Optional[Severity] = None
    photo_hint: Optional[str] = Field(default=None, max_length=500)
    lot_ids: Optional[list[UUID]] = None


class FollowUpClose(BaseModel):
    """Close it — resolved, or dismissed (it wasn't what it seemed) — with a closing bitácora entry."""
    status: Literal["resuelto", "descartado"] = "resuelto"
    notes: Optional[str] = None
    evidence: list[EventEvidence] = Field(default_factory=list)
    origin_report_id: Optional[UUID] = Field(default=None, description="The analysis that proposed it, if any")


class FollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    field_id: UUID
    zone_id: Optional[UUID] = None
    lot_ids: list[UUID] = Field(default_factory=list)
    title: str
    kind: FollowUpKind
    severity: Severity
    photo_hint: Optional[str] = None
    status: FollowUpStatus
    source: Literal["user", "agent", "system"]
    origin_report_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # From its bitácora entries:
    last_evolution: Optional[Evolution] = Field(default=None, description="At its latest evaluation")
    last_photo: Optional[str] = Field(default=None, description="Image identifier of its latest photo")
    last_photo_at: Optional[datetime] = None
    entries: int = 0


class FollowUpDetail(FollowUpRead):
    events: list[FieldEventRead] = Field(default_factory=list, description="Its bitácora entries, newest first")
