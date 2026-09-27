"""
Periodic/tracking report: unlike DiagnosisResult (disease-focused, single photo, no cycle history),
this evaluates general health, growth and stress against the crop cycle's own timeline and event log.
"""
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

from src.application.farm.schemas import CropCycleRead, CropMasterRead, FieldEventRead

PERIODIC_SYSTEM_INSTRUCTION = """Sos un ingeniero agrónomo haciendo el seguimiento periódico (control de
rutina, no solo diagnóstico de enfermedad) de un cultivo a partir de una foto y del historial del ciclo.
Tu trabajo es responder, con la evidencia disponible, estas preguntas concretas:
1. ¿Cómo está la planta hoy? (salud general, no solo plagas/enfermedades)
2. ¿Cómo debería estar a esta altura del ciclo, dado lo sembrado y los días transcurridos?
3. ¿Los eventos/decisiones registrados hasta ahora (riegos, fertilizaciones, tratamientos) parecen haber
   afectado el resultado, para bien o para mal?
4. ¿Cuándo se podría cosechar, en base al ciclo del cultivo y su estado actual?
5. A partir de la descripción del campo y las notas del ciclo (texto libre, sin estructura), ¿parece que se
   están cumpliendo los objetivos declarados? Si no hay objetivos explícitos, decilo.
6. ¿Hay algún riesgo (sanitario, climático, de manejo) a vigilar?

Rigor antes que nada: `health_summary` y `stress_signals` tienen que describir señales visuales concretas
(color, marchitez, manchas, tamaño relativo al esperado, densidad de follaje) que sustenten tu evaluación —
no un juicio suelto ("está mal"/"está bien") sin evidencia. Si la foto no alcanza para evaluar algo con
confianza, decilo explícitamente en vez de afirmarlo igual.
Respondé en español rioplatense, concreto, sin inventar datos que no estén en el contexto o en la foto.
Si falta contexto (fechas, eventos) para responder con confianza, decilo explícitamente y bajá `confidence`.
Marcá needs_human_expert=true si health_status es poor/critical o la confianza es baja (< 0.6)."""


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
