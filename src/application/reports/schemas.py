from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ReportType = Literal["diagnosis", "periodic", "soil"]


class ReportCreate(BaseModel):
    title: str = Field(default="Reporte Pendiente de Análisis", min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    status: str = Field(default="PENDING_ANALYSIS", max_length=50)
    report_type: ReportType = "diagnosis"
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    crop_cycle_ids: List[UUID] = Field(default_factory=list, description="Zone tracking: the cycles covered")
    image_identifiers: List[str] = Field(default_factory=list, description="Zone tracking: every photo")


class ReportUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    status: Optional[str] = Field(None, max_length=50)
    report_type: Optional[ReportType] = None
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None


class Report(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    field_id: Optional[UUID] = None
    crop_cycle_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    crop_cycle_ids: List[UUID] = Field(default_factory=list)
    image_identifiers: List[str] = Field(default_factory=list)
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
