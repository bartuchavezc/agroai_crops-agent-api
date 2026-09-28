"""
Periodic/tracking report: unlike DiagnosisResult (disease-focused, single photo, no cycle history),
this evaluates general health, growth and stress against the crop cycle's own timeline and event log.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.application.farm.schemas import CropCycleRead, CropMasterRead, FieldEventRead


class PeriodicReportResult(BaseModel):
    detected_crop: Optional[str] = Field(None, description="Cultivo identificado en la foto, en español")
    growth_stage: str = Field(description="Etapa fenológica observada: vegetativo, floración, fructificación, etc.")
    health_status: Literal["excellent", "good", "fair", "poor", "critical"]
    health_summary: str = Field(description="Responde: ¿cómo está la planta?")
    expected_vs_actual: str = Field(description="Responde: ¿cómo debería estar a esta altura del ciclo?")
    growth_on_track: bool
    stress_signals: list[str] = Field(default_factory=list)
    past_actions_assessment: str = Field(description="Responde: ¿las decisiones tomadas afectaron algo?")
    estimated_harvest_window: Optional[str] = Field(None, description="Texto libre, ej: 'en 2-3 semanas'")
    days_to_harvest_estimate: Optional[int] = Field(None, ge=0)
    harvest_ready: bool = Field(description="True solo si hay evidencia visual concreta de punto de cosecha")
    harvest_verdict: str = Field(description="Justificación del veredicto de cosecha, citando la señal visual")
    objectives_assessment: str = Field(description="Responde: ¿se cumplen los objetivos del campo?")
    risks: list[str] = Field(default_factory=list)
    risk_severity: Literal["low", "medium", "high", "critical"]
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_human_expert: bool


def format_cycle_progress(cycle: CropCycleRead, crop_master: Optional[CropMasterRead], today: date) -> str:
    lines = [f"Cultivo del ciclo: {crop_master.name if crop_master else 'desconocido'}"]
    if crop_master and crop_master.variety:
        lines[-1] += f" ({crop_master.variety})"
    if cycle.planting_date:
        days_elapsed = (today - cycle.planting_date).days
        lines.append(f"Sembrado/plantado el {cycle.planting_date.isoformat()} ({days_elapsed} días atrás)")
        if crop_master and crop_master.growth_period_days:
            progress_pct = round(100 * days_elapsed / crop_master.growth_period_days)
            lines.append(
                f"Ciclo típico de este cultivo: {crop_master.growth_period_days} días "
                f"(progreso estimado: {progress_pct}%)"
            )
    if cycle.expected_harvest_date:
        lines.append(f"Cosecha esperada: {cycle.expected_harvest_date.isoformat()}")
    lines.append(f"Estado del ciclo: {cycle.status}")
    if cycle.notes:
        lines.append(f"Notas del ciclo (texto libre, posible fuente de objetivos declarados): {cycle.notes}")
    return "\n".join(lines)


def format_event_history(events: list[FieldEventRead]) -> list[str]:
    lines = []
    for e in events:
        parts = [e.occurred_at.date().isoformat(), e.type]
        if e.quantity is not None:
            parts.append(f"{e.quantity} {e.unit or ''}".strip())
        if e.notes:
            parts.append(e.notes)
        lines.append(" - ".join(parts))
    return lines
