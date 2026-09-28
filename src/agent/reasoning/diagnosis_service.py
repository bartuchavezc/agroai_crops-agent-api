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

from ..prompts.diagnosis import SYSTEM_INSTRUCTION
from ..prompts.harvest import HARVEST_VERDICT_INSTRUCTION
from ..prompts.knowledge_ar import modules_for_account
from ..prompts.periodic import PERIODIC_SYSTEM_INSTRUCTION
from ..prompts.soil import SOIL_SYSTEM_INSTRUCTION
from ..providers.gemini import GeminiGateway
from ..schemas import DiagnosisResult, HarvestVerdictResult, SoilRecognitionResult
from .periodic_report import PeriodicReportResult, format_cycle_progress, format_event_history

logger = logging.getLogger(__name__)


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
            if report.report_type == "soil":
                return await self._analyze_soil(actor, report, image_identifier)
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

    async def _analyze_soil(self, actor: Actor, report: Report, image_identifier: Optional[str] = None) -> dict:
        """Soil-sample photo recognition: apparent type/porosity only, never nutrient levels (see soil prompt)."""
        report_id = report.id
        image_bytes, mime_type, image_id = await self._load_image(actor, report, image_identifier)

        context_lines, _ = await self._field_context(actor, report.field_id)
        prompt = "Identificá el tipo de suelo aparente y la porosidad/drenaje a partir de la foto de la muestra."
        if context_lines:
            prompt += "\n\nContexto del lote:\n" + "\n".join(f"- {line}" for line in context_lines)

        result: SoilRecognitionResult = await self.gemini.generate_structured(
            actor.user_id,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            schema=SoilRecognitionResult,
            system_instruction=SOIL_SYSTEM_INSTRUCTION,
        )

        await self.reports.update_report(
            actor,
            report_id,
            ReportUpdate(
                title="Muestra de suelo",
                summary=f"{result.apparent_soil_type}, porosidad {result.apparent_porosity}",
                recommendations="\n".join(result.companion_planting_suggestions),
                status="ANALYSIS_COMPLETED",
                raw_analysis_data={
                    "llm_structured_soil": result.model_dump(),
                    "analyzed_image_identifier": image_id,
                    "model": self.gemini.model,
                },
            ),
        )
        await self.notifications.notify_account(
            account_id=actor.account_id,
            exclude_user_id=actor.user_id,
            type="report_soil",
            title="Nuevo análisis de suelo",
            message=result.drainage_note,
            entity_type="report",
            entity_id=report_id,
            field_id=report.field_id,
        )
        return {
            "status": "success",
            "report_id": str(report_id),
            "caption": f"{result.apparent_soil_type}, porosidad {result.apparent_porosity}",
            "soil": result.model_dump(),
            "metadata": {
                "confidence": result.confidence,
                "needs_human_expert": result.needs_human_expert,
            },
        }

    async def harvest_verdict(
        self,
        actor: Actor,
        field_id: Optional[UUID],
        crop_cycle_id: Optional[UUID] = None,
        image_identifier: Optional[str] = None,
    ) -> dict:
        """Standalone, non-persisting "ready to harvest?" check. With a fresh photo, a lightweight Gemini call
        (no report saved). Without one, falls back to the harvest_ready/harvest_verdict already produced by
        the latest periodic report of this field/cycle."""
        if image_identifier:
            image_bytes, mime_type = await self.storage.get_image_for_model(
                actor, image_identifier, self.max_image_side
            )
            context_lines, _ = await self._field_context(actor, field_id)
            context_lines += await self._periodic_context(actor, field_id, crop_cycle_id)
            prompt = "¿Está lista para cosechar la planta/fruto de la foto?"
            if context_lines:
                prompt += "\n\nContexto:\n" + "\n".join(f"- {line}" for line in context_lines)

            result: HarvestVerdictResult = await self.gemini.generate_structured(
                actor.user_id,
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
                schema=HarvestVerdictResult,
                system_instruction=HARVEST_VERDICT_INSTRUCTION,
            )
            return {
                "source": "photo",
                "ready": result.ready,
                "verdict": result.verdict,
                "confidence": result.confidence,
            }

        reports = await self.reports.list_reports(
            actor, field_id=field_id, crop_cycle_id=crop_cycle_id, report_type="periodic", limit=1
        )
        completed = [r for r in reports if r.status == "ANALYSIS_COMPLETED"]
        if not completed:
            raise InvalidInputError(
                "No hay foto en este turno ni un reporte periódico previo de este campo/ciclo para basar un "
                "veredicto de cosecha. Pedí una foto o hacé un seguimiento periódico primero."
            )
        latest = completed[0]
        periodic = (latest.raw_analysis_data or {}).get("llm_structured_periodic") or {}
        return {
            "source": "latest_periodic_report",
            "report_date": latest.created_at.date().isoformat(),
            "ready": periodic.get("harvest_ready", False),
            "verdict": periodic.get("harvest_verdict", "Sin veredicto de cosecha en el último reporte."),
        }
