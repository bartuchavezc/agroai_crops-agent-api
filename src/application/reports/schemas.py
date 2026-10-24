from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReportType = Literal["diagnosis", "periodic", "soil"]
PhotoRoleName = Literal["general", "detalle", "seguimiento"]


class PhotoRole(BaseModel):
    """What one zone-tracking photo shows, in the order of `image_identifiers`: the analysis hands each pass
    only the photos it needs (the overview the general ones, a crop group its own close-ups) instead of
    every photo to every call — a zone analysis is several Gemini calls, and photos are most of their size."""
    role: PhotoRoleName
    lot_id: Optional[UUID] = Field(None, description="The lot a close-up / follow-up photo is of; none = the zone")
    hint: Optional[str] = Field(None, max_length=200, description='What was asked for ("envés de las hojas")')


class ReportCreate(BaseModel):
    title: str = Field(default="Reporte Pendiente de Análisis", min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    status: str = Field(default="PENDING_ANALYSIS", max_length=50)
    report_type: ReportType = "diagnosis"
    field_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_ids: List[UUID] = Field(default_factory=list, description="Zone tracking: the lots covered")
    image_identifiers: List[str] = Field(default_factory=list, description="Zone tracking: every photo")
    photo_roles: List[PhotoRole] = Field(default_factory=list, description="Zone tracking: one per photo, or none")
    notes: Optional[str] = Field(None, max_length=2000, description="The user's own observations, fed to the model")
    reason: Optional[str] = Field(None, max_length=500, description='Why it was taken ("motivo")')


class ReportUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, max_length=50)
    report_type: Optional[ReportType] = None
    field_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    reason: Optional[str] = Field(None, max_length=500)


class Report(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    lot_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    lot_ids: List[UUID] = Field(default_factory=list)
    image_identifiers: List[str] = Field(default_factory=list)
    photo_roles: List[PhotoRole] = Field(default_factory=list)
    notes: Optional[str] = None
    reason: Optional[str] = None
    created_by: Optional[UUID] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    analysis_id: Optional[UUID] = None
    status: str
    report_type: ReportType = "diagnosis"
    created_at: datetime
    updated_at: datetime
