"""
Multimodal crop analysis: the photo goes straight to Gemini together with the field/cycle context.
Two report types share this service:
- "diagnosis": disease/pest/nutrition focused, single photo, no cycle history (DiagnosisResult).
- "periodic": routine tracking (health/growth/stress/harvest/objectives/risks), grounded in the crop
  cycle's timeline and event log (PeriodicReportResult).
"""
import logging
from datetime import date
from typing import Optional
from uuid import UUID

from google.genai import types

from src.application.alerts.rules_engine import RulesEngine
from src.application.farm.service import FarmService
from src.application.notifications.service import NotificationService
from src.application.reports.schemas import Report, ReportUpdate
from src.application.reports.service import ReportsService
from src.application.storage.service import StorageService
from src.auth.services.profile_service import ProfileService
from src.providers.weather.service import WeatherService
from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

from ..knowledge_ar import modules_for_account
from ..providers.gemini import GeminiGateway
from ..schemas import DiagnosisResult
from .periodic_report import (
    PERIODIC_SYSTEM_INSTRUCTION,
    PeriodicReportResult,
    format_cycle_progress,
    format_event_history,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """Sos un ingeniero agrónomo especializado en huertas y cultivos hortícolas,
patología vegetal, plagas y nutrición. Analizás la foto que te envían y el contexto del lote.
- Respondé en español rioplatense, claro y concreto.
- Rigor antes que nada: primero describí en `visual_evidence` lo que efectivamente se ve en la foto (color,
  forma y distribución de las manchas/lesiones, qué partes de la planta están afectadas, patrón de avance) —
  hechos observables, no un veredicto. Recién después nombrá la causa en `general_diagnosis`, y esa causa
  tiene que quedar justificada por lo que describiste en `visual_evidence`, no ser una conclusión sin sustento.
- Si la evidencia visual es compatible con más de una causa (p. ej. dos hongos con síntomas parecidos), decilo
  explícitamente, listá las alternativas plausibles en `possible_causes` (no solo la más probable) y bajá la
  confianza en consecuencia — no fuerces una única respuesta cuando la foto no alcanza para diferenciar.
- Reservá confidence alta (> 0.8) para cuando el patrón, color y ubicación sean característicos e inequívocos;
  si hay señales pero no alcanzan para confirmar la causa exacta, decilo en vez de adivinar.
- Diagnosticá solo lo que se ve o se infiere con fundamento; si la foto no alcanza, decilo y bajá la confianza.
- Priorizá manejo integrado y alternativas de bajo impacto; indicá dosis solo si son estándar y seguras.
- Marcá needs_human_expert=true si la severidad es alta o la confianza es baja (< 0.6)."""


class DiagnosisService:
    def __init__(
        self,
        gemini: GeminiGateway,
        storage_service: StorageService,
        reports_service: ReportsService,
        farm_service: FarmService,
        weather_service: WeatherService,
        rules_engine: RulesEngine,
        profile_service: ProfileService,
        notification_service: NotificationService,
        max_image_side: int = 1536,
    ):
        self.gemini = gemini
        self.storage = storage_service
        self.reports = reports_service
        self.farm = farm_service
        self.weather = weather_service
        self.rules = rules_engine
        self.profiles = profile_service
        self.notifications = notification_service
        self.max_image_side = max_image_side

    async def _field_context(self, actor: Actor, field_id: Optional[UUID]) -> tuple[list[str], dict]:
        lines: list[str] = []
        weather: dict = {}
        if not field_id:
            return lines, weather
        field = await self.farm.get_field(actor, field_id)
        lines.append(f"Lote: {field.name}" + (f" ({field.city})" if field.city else ""))
        if field.soil_type:
            lines.append(f"Suelo: {field.soil_type}")
        for overview in await self.farm.overview(actor):
            if overview.field.id == field_id and overview.active_cycles:
                crops = ", ".join(
                    f"{c.crop_name}{' ' + c.variety if c.variety else ''} ({c.status})" for c in overview.active_cycles
                )
                lines.append(f"Cultivos activos: {crops}")
        if field.latitude is not None and field.longitude is not None:
            try:
                weather = await self.weather.current(field.latitude, field.longitude) or {}
            except Exception as e:  # weather is optional context
                logger.warning(f"Weather unavailable for diagnosis: {e}")
            if weather:
                lines.append(
                    f"Clima actual: {weather.get('temperature')}°C, humedad {weather.get('humidity')}%, "
                    f"{weather.get('description') or ''}"
                )
        return lines, weather

    async def _periodic_context(
        self, actor: Actor, field_id: Optional[UUID], crop_cycle_id: Optional[UUID]
    ) -> list[str]:
        lines: list[str] = []
        if not crop_cycle_id:
            return lines
        cycle = await self.farm.get_crop_cycle(actor, crop_cycle_id)
        crop_master = await self.farm.get_crop_master(actor, cycle.crop_master_id) if cycle.crop_master_id else None
        lines.append(format_cycle_progress(cycle, crop_master, date.today()))

        events = await self.farm.list_events(actor, crop_cycle_id=crop_cycle_id, limit=50)
        if events:
            lines.append("Historial de eventos del ciclo (decisiones/manejo registrado):")
            lines.extend(f"- {line}" for line in format_event_history(events))
        else:
            lines.append("No hay eventos registrados para este ciclo todavía.")

        previous = await self.reports.list_reports(
            actor, crop_cycle_id=crop_cycle_id, report_type="periodic", limit=3
        )
        previous = [r for r in previous if r.status == "ANALYSIS_COMPLETED"]
        if previous:
            lines.append("Análisis periódicos previos de este mismo ciclo (más reciente primero):")
            for r in previous:
                summary = r.summary or "(sin resumen)"
                lines.append(f"- {r.created_at.date().isoformat()}: {summary}")

        if field_id:
            field = await self.farm.get_field(actor, field_id)
            if field.description:
                lines.append(f"Descripción del campo (posible fuente de objetivos declarados): {field.description}")
        return lines

    async def _load_image(
        self, actor: Actor, report: Report, image_identifier: Optional[str]
    ) -> tuple[bytes, str, str]:
        image_id = image_identifier or report.image_identifier
        if not image_id:
            raise InvalidInputError("The report has no image to analyze.")
        image_bytes, mime_type = await self.storage.get_image_for_model(actor, image_id, self.max_image_side)
        return image_bytes, mime_type, image_id

    async def analyze(self, actor: Actor, report_id: UUID, image_identifier: Optional[str] = None) -> dict:
        report = await self.reports.get_report(actor, report_id)
        try:
            if report.report_type == "periodic":
                return await self._analyze_periodic(actor, report, image_identifier)
            return await self._analyze_diagnosis(actor, report, image_identifier)
        except Exception:
            # Persist the failure (quota exhausted, model overloaded, etc.) so the report doesn't stay
            # stuck at PENDING_ANALYSIS with no visible way out — the UI offers a "Reintentar" button
            # for ANALYSIS_FAILED. The original error still propagates to whoever called analyze().
            try:
                await self.reports.update_report(actor, report_id, ReportUpdate(status="ANALYSIS_FAILED"))
            except Exception:
                logger.exception(f"Could not mark report {report_id} as failed")
            raise

    async def _analyze_diagnosis(self, actor: Actor, report: Report, image_identifier: Optional[str] = None) -> dict:
        report_id = report.id
        image_bytes, mime_type, image_id = await self._load_image(actor, report, image_identifier)

        context_lines, weather = await self._field_context(actor, report.field_id)
        weather_rules = self.rules.evaluate(
            {"temperature": weather.get("temperature", 20), "humidity": weather.get("humidity", 50)},
            categories=["weather", "disease"],
        ) if weather else []
        if weather_rules:
            context_lines.append("Alertas por reglas: " + " | ".join(r.message for r in weather_rules))

        prompt = "Diagnosticá el estado del cultivo en la foto."
        if context_lines:
            prompt += "\n\nContexto del lote:\n" + "\n".join(f"- {line}" for line in context_lines)

        profile = await self.profiles.get_profile_context(actor.user_id)
        crop_families = await self.farm.crop_families(actor)
        field_texts = [line for line in context_lines if "Suelo:" in line]
        knowledge = modules_for_account(
            profile.calculated_profile if profile else None, crop_families, field_texts
        )

        diagnosis: DiagnosisResult = await self.gemini.generate_structured(
            actor.user_id,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            schema=DiagnosisResult,
            system_instruction=f"{SYSTEM_INSTRUCTION}\n\n{knowledge}",
        )

        area_rules = self.rules.evaluate(
            {"affected_percentage": diagnosis.affected_area_percent or 0}, categories=["health"]
        )
        rule_alerts = [
            {"rule": r.rule_id, "severity": r.severity.value, "message": r.message} for r in weather_rules + area_rules
        ]
        recommendations = [f"{t.title}: {t.description}" for t in diagnosis.recommended_treatments]
        recommendations += diagnosis.specific_recommendations

        await self.reports.update_report(
            actor,
            report_id,
            ReportUpdate(
                title=(diagnosis.detected_crop or "Diagnóstico")[:255],
                summary=diagnosis.general_diagnosis,
                recommendations="\n".join(recommendations),
                status="ANALYSIS_COMPLETED",
                raw_analysis_data={
                    "llm_structured_diagnosis": diagnosis.model_dump(),
                    "affected_percentage": diagnosis.affected_area_percent,
                    "rule_alerts": rule_alerts,
                    "weather": weather,
                    "analyzed_image_identifier": image_id,
                    "model": self.gemini.model,
                },
            ),
        )
        await self.notifications.notify_account(
            account_id=actor.account_id,
            exclude_user_id=actor.user_id,
            type="report_diagnosis",
            title="Nuevo diagnóstico",
            message=diagnosis.general_diagnosis,
            entity_type="report",
            entity_id=report_id,
            field_id=report.field_id,
        )
        return {
            "status": "success",
            "report_id": str(report_id),
            "caption": diagnosis.general_diagnosis,
            "diagnosis": diagnosis.model_dump(),
            "severity": diagnosis.severity,
            "recommendations": recommendations,
            "metadata": {
                "affected_percentage": diagnosis.affected_area_percent,
                "rules_triggered": len(rule_alerts),
                "confidence": diagnosis.confidence,
                "needs_human_expert": diagnosis.needs_human_expert,
            },
        }

    async def _analyze_periodic(self, actor: Actor, report: Report, image_identifier: Optional[str] = None) -> dict:
        report_id = report.id
        image_bytes, mime_type, image_id = await self._load_image(actor, report, image_identifier)

        context_lines, weather = await self._field_context(actor, report.field_id)
        context_lines += await self._periodic_context(actor, report.field_id, report.crop_cycle_id)

        prompt = "Hacé el seguimiento periódico del cultivo en la foto (no es solo diagnóstico de enfermedad)."
        if context_lines:
            prompt += "\n\nContexto del campo y del ciclo:\n" + "\n".join(f"- {line}" for line in context_lines)

        profile = await self.profiles.get_profile_context(actor.user_id)
        crop_families = await self.farm.crop_families(actor)
        field_texts = [line for line in context_lines if "Suelo:" in line]
        knowledge = modules_for_account(
            profile.calculated_profile if profile else None, crop_families, field_texts
        )

        result: PeriodicReportResult = await self.gemini.generate_structured(
            actor.user_id,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            schema=PeriodicReportResult,
            system_instruction=f"{PERIODIC_SYSTEM_INSTRUCTION}\n\n{knowledge}",
        )

        await self.reports.update_report(
            actor,
            report_id,
            ReportUpdate(
                title=(result.detected_crop or "Seguimiento periódico")[:255],
                summary=result.health_summary,
                recommendations="\n".join(result.recommendations),
                status="ANALYSIS_COMPLETED",
                raw_analysis_data={
                    "llm_structured_periodic": result.model_dump(),
                    "weather": weather,
                    "analyzed_image_identifier": image_id,
                    "model": self.gemini.model,
                },
            ),
        )
        await self.notifications.notify_account(
            account_id=actor.account_id,
            exclude_user_id=actor.user_id,
            type="report_periodic",
            title="Nuevo reporte de seguimiento",
            message=result.health_summary,
            entity_type="report",
            entity_id=report_id,
            field_id=report.field_id,
        )
        return {
            "status": "success",
            "report_id": str(report_id),
            "caption": result.health_summary,
            "analysis": result.model_dump(),
            "risk_severity": result.risk_severity,
            "recommendations": result.recommendations,
            "metadata": {
                "confidence": result.confidence,
                "needs_human_expert": result.needs_human_expert,
            },
        }
