# src/action/reports/schemas.py
"""
Report schemas and models.
"""
from uuid import UUID, uuid4
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ReportBase(BaseModel):
    """Base report schema."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    analysis_id: Optional[UUID] = None
    status: str = Field(default="PENDING_ANALYSIS")


class ReportCreate(ReportBase):
    """Schema for creating a report."""
    image_identifier: str  # Required when creating
    title: str = Field(
        default="Reporte Pendiente de Análisis",
        min_length=1,
        max_length=255
    )


class ReportUpdate(BaseModel):
    """Schema for updating a report."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = None
    recommendations: Optional[str] = None
    image_identifier: Optional[str] = None
    raw_analysis_data: Optional[Dict[str, Any]] = None
    analysis_id: Optional[UUID] = None
    status: Optional[str] = None


class Report(ReportBase):
    """Full report schema with ID and timestamps."""
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {
        "from_attributes": True
    }
