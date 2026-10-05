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


# ---------- zone tracking (daily follow-up of a whole cajón / cantero / invernadero / hidroponía) ----------

class ZoneCropAssessment(BaseModel):
    crop_cycle_id: str = Field(description="El id del ciclo EXACTAMENTE como figura en el contexto")
    crop_name: str
    visible_in_photos: bool = Field(description="False si este cultivo no se distingue en ninguna foto")
    growth_stage: str = Field(description="Etapa fenológica observada; 'no visible' si no se ve")
    health_status: Literal["excellent", "good", "fair", "poor", "critical", "unknown"]
    health_summary: str = Field(description="¿Cómo está este cultivo? Citando señales visuales concretas")
    expected_vs_actual: str = Field(description="¿Cómo debería estar a esta altura del ciclo?")
    growth_on_track: Optional[bool] = None
    stress_signals: list[str] = Field(default_factory=list)
    estimated_harvest_window: Optional[str] = None
    days_to_harvest_estimate: Optional[int] = Field(None, ge=0)
    harvest_ready: bool = Field(description="True solo con evidencia visual concreta de punto de cosecha")
    harvest_verdict: str
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ZonePeriodicReportResult(BaseModel):
    zone_summary: str = Field(description="¿Cómo viene la zona en conjunto? 2-4 oraciones")
    overall_health: Literal["excellent", "good", "fair", "poor", "critical"]
    crops: list[ZoneCropAssessment] = Field(description="Una entrada por cada ciclo listado en el contexto")
    unlisted_plants: list[str] = Field(
        default_factory=list, description="Plantas que se ven en las fotos pero no están registradas en la zona"
    )
    interactions: Optional[str] = Field(
        None, description="Competencia, sombra entre cultivos, asociaciones favorables/desfavorables"
    )
    past_actions_assessment: str = Field(description="¿Las decisiones registradas afectaron algo?")
    objectives_assessment: str
    shared_risks: list[str] = Field(default_factory=list, description="Riesgos que afectan a toda la zona")
    risk_severity: Literal["low", "medium", "high", "critical"]
    recommendations: list[str] = Field(default_factory=list, description="Para la zona en conjunto")
    confidence: float = Field(ge=0, le=1)
    needs_human_expert: bool


def crop_entry(analysis: dict, crop_cycle_id) -> Optional[dict]:
    """The entry of one cycle inside a zone report's structured analysis (llm_structured_zone)."""
    for crop in analysis.get("crops") or []:
        if crop.get("crop_cycle_id") == str(crop_cycle_id):
            return crop
    return None
