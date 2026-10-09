"""
Multimodal crop analysis: the photo goes straight to Gemini together with the field/cycle context.
Two report types share this service:
- "diagnosis": disease/pest/nutrition focused, single photo, no cycle history (DiagnosisResult).
- "periodic": routine tracking (health/growth/stress/harvest/objectives/risks), grounded in the crop
  cycle's timeline and event log (PeriodicReportResult). A periodic report of a zone (cajón, cantero,
  invernadero, hidroponía) covers every active crop of the zone at once, from 1-4 photos
  (ZonePeriodicReportResult, stored as llm_structured_zone).
"""
import logging
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
from src.shared.domain.locale import localized, today_in
from src.shared.utils.errors import InvalidInputError

from ..prompts.analysis import ANALYSIS_GROUNDING, DEEP_REFINE_INSTRUCTION
from ..prompts.diagnosis import SYSTEM_INSTRUCTION
from ..prompts.harvest import HARVEST_VERDICT_INSTRUCTION
from ..prompts.knowledge import modules_for
from ..prompts.periodic import PERIODIC_SYSTEM_INSTRUCTION, ZONE_PERIODIC_SYSTEM_INSTRUCTION
from ..prompts.soil import SOIL_SYSTEM_INSTRUCTION
from ..prompts.voice import localize
from ..providers.gemini import GeminiGateway
from ..schemas import DiagnosisResult, HarvestVerdictResult, SoilRecognitionResult
from .analysis_context import AnalysisContext, AnalysisContextBuilder, to_json
from .periodic_report import (
    PeriodicReportResult,
    ZonePeriodicReportResult,
    crop_entry,
    format_cycle_progress,
    format_event_history,
)

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
        satellite_service,
        search=None,
        max_image_side: int = 1536,
        deep_default: bool = True,
        field_rules=None,
    ):
        self.gemini = gemini
        self.storage = storage_service
        self.reports = reports_service
        self.farm = farm_service
        self.weather = weather_service
        self.rules = rules_engine
        self.field_rules = field_rules  # FieldAlertRulesService: what each field switched off or tuned
        self.profiles = profile_service
        self.notifications = notification_service
        self.max_image_side = max_image_side
        self.deep_default = deep_default
        self.analysis_context = AnalysisContextBuilder(
            farm_service, reports_service, weather_service, satellite_service, search
        )

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
                    f"{localized(c.crop_name, c.crop_i18n, actor.locale)}"
                    f"{' ' + c.variety if c.variety else ''} ({c.status})"
                    for c in overview.active_cycles
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
        lines.append(format_cycle_progress(cycle, crop_master, today_in(actor.timezone)))

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
                entry = crop_entry((r.raw_analysis_data or {}).get("llm_structured_zone") or {}, crop_cycle_id)
                summary = (entry or {}).get("health_summary") or r.summary or "(sin resumen)"
                lines.append(f"- {r.created_at.date().isoformat()}: {summary}")

        if field_id:
            field = await self.farm.get_field(actor, field_id)
            if field.description:
                lines.append(f"Descripción del campo (posible fuente de objetivos declarados): {field.description}")
        return lines

    async def _crops_in_scope(self, actor: Actor, report: Report) -> list[str]:
        """Crop names of what the report is about: its cycle(s), else every active cycle of its field."""
        if not report.field_id:
            return []
        overview = [o for o in await self.farm.overview(actor) if o.field.id == report.field_id]
        cycles = overview[0].active_cycles if overview else []
        ids = set(getattr(report, "crop_cycle_ids", None) or [])
        if report.crop_cycle_id:
            ids.add(report.crop_cycle_id)
        picked = [c for c in cycles if c.id in ids] if ids else cycles
        return list(dict.fromkeys(c.crop_name for c in (picked or cycles)))

    async def _analysis_context(self, actor: Actor, report: Report, kind: str) -> AnalysisContext:
        """The references and field data this kind of analysis needs (see analysis_context.py)."""
        if not report.field_id:
            text, loaded = self.analysis_context.references_for(self.analysis_context.crop_reference_names([]))
            return AnalysisContext(references=text, loaded=loaded)
        crops = await self._crops_in_scope(actor, report)
        try:
            # Soil analyses need the SoilGrids numbers: fetched the first time and cached in the field.
            field = await (self.farm.ensure_soilgrids(actor, report.field_id) if kind == "soil"
                           else self.farm.get_field(actor, report.field_id))
            builder = self.analysis_context.for_soil if kind == "soil" else self.analysis_context.for_crop
            context = await builder(actor, report, field, crops)
        except Exception:  # noqa: BLE001 - the analysis still runs on the photo and the basic context
            logger.exception("Analysis context failed; continuing with the photo and the basic context")
            return AnalysisContext()
        context.crops = crops
        return context

    async def _structured(
        self, actor: Actor, *, parts: list, prompt: str, schema, instruction: str, knowledge: str,
        analysis: AnalysisContext, deep: Optional[bool], notable, findings,
    ):
        """One analysis: the first pass over photo + context + references, then (when asked and worth it) the deep
        pass — web research on what the first pass found, and the analysis refined with it at the highest reasoning
        depth. Returns (result, research) where `research` says what went into it."""
        system = localize(
            f"{instruction}\n\n{ANALYSIS_GROUNDING}\n\n{knowledge}\n\n"
            f"# Material de referencia\n\n{analysis.references}",
            actor.country,
        )
        if analysis.data_lines:
            prompt += "\n\nDatos del campo y registros:\n" + "\n".join(f"- {line}" for line in analysis.data_lines)
        result = await self.gemini.generate_structured(
            actor.user_id, contents=[*parts, prompt], schema=schema, system_instruction=system, thinking_level="medium",
        )
        research: dict = {"references": analysis.loaded, "deep": False}
        wanted = self.deep_default if deep is None else deep
        if wanted and notable(result):
            queries = self.analysis_context.queries_for(analysis.crops, findings(result), actor.country)
            text, sources = await self.analysis_context.research(queries)
            research.update({"queries": queries, "sources": sources})
            if text:
                refined_prompt = (
                    f"{prompt}\n\n## Tu primer análisis (a refinar)\n{to_json(result)}\n\n"
                    f"## Fuentes consultadas en la web\n{text}\n\n{DEEP_REFINE_INSTRUCTION}"
                )
                result = await self.gemini.generate_structured(
                    actor.user_id, contents=[*parts, refined_prompt], schema=schema, system_instruction=system,
                    thinking_level="high",
                )
                research["deep"] = True
        return result, research

    async def _load_image(
        self, actor: Actor, report: Report, image_identifier: Optional[str]
    ) -> tuple[bytes, str, str]:
        image_id = image_identifier or report.image_identifier
        if not image_id:
            raise InvalidInputError("The report has no image to analyze.")
        image_bytes, mime_type = await self.storage.get_image_for_model(actor, image_id, self.max_image_side)
        return image_bytes, mime_type, image_id

    async def analyze(
        self, actor: Actor, report_id: UUID, image_identifier: Optional[str] = None, deep: Optional[bool] = None
    ) -> dict:
        """`deep`: None = the deployment default (`ANALYSIS_DEEP`); True/False force the web-research second pass on
        or off. It only runs when the first pass found something worth the extra cost (a risk, a disease, low
        confidence)."""
        report = await self.reports.get_report(actor, report_id)
        try:
            if report.report_type == "periodic" and report.zone_id and report.crop_cycle_id is None:
                return await self._analyze_zone(actor, report, deep)
            if report.report_type == "periodic":
                return await self._analyze_periodic(actor, report, image_identifier, deep)
            if report.report_type == "soil":
                return await self._analyze_soil(actor, report, image_identifier)
            return await self._analyze_diagnosis(actor, report, image_identifier, deep)
        except Exception:
            # Persist the failure (quota exhausted, model overloaded, etc.) so the report doesn't stay
            # stuck at PENDING_ANALYSIS with no visible way out — the UI offers a "Reintentar" button
            # for ANALYSIS_FAILED. The original error still propagates to whoever called analyze().
            try:
                await self.reports.update_report(actor, report_id, ReportUpdate(status="ANALYSIS_FAILED"))
            except Exception:
                logger.exception(f"Could not mark report {report_id} as failed")
            raise

    async def _rule_overrides(self, field_id) -> dict:
        return await self.field_rules.overrides(field_id) if (self.field_rules and field_id) else {}

    async def _analyze_diagnosis(
        self, actor: Actor, report: Report, image_identifier: Optional[str] = None, deep: Optional[bool] = None
    ) -> dict:
        report_id = report.id
        image_bytes, mime_type, image_id = await self._load_image(actor, report, image_identifier)

        context_lines, weather = await self._field_context(actor, report.field_id)
        overrides = await self._rule_overrides(report.field_id)
        weather_rules = self.rules.evaluate(
            {"temperature": weather.get("temperature", 20), "humidity": weather.get("humidity", 50)},
            categories=["weather", "disease"], overrides=overrides,
        ) if weather else []
        if weather_rules:
            context_lines.append("Alertas por reglas: " + " | ".join(r.message for r in weather_rules))

        prompt = "Diagnosticá el estado del cultivo en la foto."
        if context_lines:
            prompt += "\n\nContexto del lote:\n" + "\n".join(f"- {line}" for line in context_lines)

        profile = await self.profiles.get_profile_context(actor.user_id)
        crop_families = await self.farm.crop_families(actor)
        field_texts = [line for line in context_lines if "Suelo:" in line]
        knowledge = modules_for(
            actor.country, profile.calculated_profile if profile else None, crop_families, field_texts
        )

        analysis = await self._analysis_context(actor, report, "crop")
        diagnosis, research = await self._structured(
            actor,
            parts=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            prompt=prompt,
            schema=DiagnosisResult,
            instruction=SYSTEM_INSTRUCTION,
            knowledge=knowledge,
            analysis=analysis,
            deep=deep,
            notable=lambda d: d.severity != "low" or d.likely_category not in ("healthy",) or d.confidence < 0.75
            or d.needs_human_expert,
            findings=lambda d: [d.general_diagnosis, *d.possible_causes[:2]],
        )
        if research.get("sources"):
            diagnosis.additional_notes = (diagnosis.additional_notes + "\n\nFuentes consultadas: " + "; ".join(
                f"{x['title']} ({x['url']})" for x in research["sources"][:5])).strip()

        area_rules = self.rules.evaluate(
            {"affected_percentage": diagnosis.affected_area_percent or 0}, categories=["health"], overrides=overrides
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
                    "research": research,
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

    async def _analyze_periodic(
        self, actor: Actor, report: Report, image_identifier: Optional[str] = None, deep: Optional[bool] = None
    ) -> dict:
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
        knowledge = modules_for(
            actor.country, profile.calculated_profile if profile else None, crop_families, field_texts
        )

        analysis = await self._analysis_context(actor, report, "crop")
        result, research = await self._structured(
            actor,
            parts=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            prompt=prompt,
            schema=PeriodicReportResult,
            instruction=PERIODIC_SYSTEM_INSTRUCTION,
            knowledge=knowledge,
            analysis=analysis,
            deep=deep,
            notable=lambda r: r.risk_severity != "low" or r.health_status in ("fair", "poor", "critical")
            or r.confidence < 0.7 or r.needs_human_expert,
            findings=lambda r: [*r.stress_signals[:2], *r.risks[:1]] or [r.health_summary],
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
                    "research": research,
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

    async def _zone_context(self, actor: Actor, report: Report) -> list[str]:
        zone = await self.farm.get_zone(actor, report.zone_id)
        lines = [f"Zona: {zone.label}" + (f". Notas: {zone.notes}" if zone.notes else "")]
        today = today_in(actor.timezone)
        if not report.crop_cycle_ids:
            lines.append("La zona no tiene ciclos de cultivo activos registrados.")
        for cycle_id in report.crop_cycle_ids:
            cycle = await self.farm.get_crop_cycle(actor, cycle_id)
            crop_master = await self.farm.get_crop_master(actor, cycle.crop_master_id)
            lines.append(f"Ciclo crop_cycle_id={cycle.id}:")
            lines.append(format_cycle_progress(cycle, crop_master, today))
            events = await self.farm.list_events(actor, crop_cycle_id=cycle.id, limit=20)
            if events:
                lines.append("Eventos del ciclo: " + "; ".join(format_event_history(events)))
        zone_events = [
            e for e in await self.farm.list_events(actor, field_id=report.field_id, zone_id=zone.id, limit=50)
            if e.crop_cycle_id is None
        ]
        if zone_events:
            lines.append("Eventos de la zona en general: " + "; ".join(format_event_history(zone_events[:20])))
        previous = [
            r for r in await self.reports.list_reports(actor, zone_id=zone.id, report_type="periodic", limit=4)
            if r.status == "ANALYSIS_COMPLETED" and r.id != report.id
        ][:3]
        if previous:
            lines.append("Seguimientos previos de esta zona (más reciente primero):")
            lines.extend(f"- {r.created_at.date().isoformat()}: {r.summary or '(sin resumen)'}" for r in previous)
        if report.field_id:
            field = await self.farm.get_field(actor, report.field_id)
            if field.description:
                lines.append(f"Descripción del campo (posible fuente de objetivos declarados): {field.description}")
        return lines

    async def _analyze_zone(self, actor: Actor, report: Report, deep: Optional[bool] = None) -> dict:
        """Daily tracking of a whole zone: every photo of the report, every active crop of the zone."""
        image_ids = report.image_identifiers or ([report.image_identifier] if report.image_identifier else [])
        if not image_ids:
            raise InvalidInputError("The report has no image to analyze.")
        parts = []
        for image_id in image_ids:
            data, mime_type = await self.storage.get_image_for_model(actor, image_id, self.max_image_side)
            parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

        context_lines, weather = await self._field_context(actor, report.field_id)
        context_lines += await self._zone_context(actor, report)
        prompt = (
            f"Hacé el seguimiento diario de la zona completa ({len(image_ids)} foto/s): cómo viene la zona y cada "
            "uno de sus cultivos.\n\nContexto del campo, la zona y sus ciclos:\n"
            + "\n".join(f"- {line}" for line in context_lines)
        )
        profile = await self.profiles.get_profile_context(actor.user_id)
        crop_families = await self.farm.crop_families(actor)
        field_texts = [line for line in context_lines if "Suelo:" in line]
        knowledge = modules_for(
            actor.country, profile.calculated_profile if profile else None, crop_families, field_texts
        )

        analysis = await self._analysis_context(actor, report, "crop")
        result, research = await self._structured(
            actor,
            parts=parts,
            prompt=prompt,
            schema=ZonePeriodicReportResult,
            instruction=ZONE_PERIODIC_SYSTEM_INSTRUCTION,
            knowledge=knowledge,
            analysis=analysis,
            deep=deep,
            notable=lambda r: r.risk_severity != "low" or r.confidence < 0.7 or r.needs_human_expert,
            findings=lambda r: [r.zone_summary],
        )
        zone = await self.farm.get_zone(actor, report.zone_id)
        await self.reports.update_report(
            actor,
            report.id,
            ReportUpdate(
                title=f"{zone.label} · seguimiento"[:255],
                summary=result.zone_summary,
                recommendations="\n".join(result.recommendations),
                status="ANALYSIS_COMPLETED",
                raw_analysis_data={
                    "llm_structured_zone": result.model_dump(),
                    "weather": weather,
                    "research": research,
                    "analyzed_image_identifiers": image_ids,
                    "model": self.gemini.model,
                },
            ),
        )
        await self.notifications.notify_account(
            account_id=actor.account_id,
            exclude_user_id=actor.user_id,
            type="report_periodic",
            title=f"Nuevo seguimiento: {zone.label}",
            message=result.zone_summary,
            entity_type="report",
            entity_id=report.id,
            field_id=report.field_id,
        )
        return {
            "status": "success",
            "report_id": str(report.id),
            "caption": result.zone_summary,
            "analysis": result.model_dump(),
            "risk_severity": result.risk_severity,
            "recommendations": result.recommendations,
            "metadata": {"confidence": result.confidence, "needs_human_expert": result.needs_human_expert},
        }

    async def _analyze_soil(self, actor: Actor, report: Report, image_identifier: Optional[str] = None) -> dict:
        """Soil-sample photo recognition (apparent type/porosity, never nutrient levels from the photo) read together
        with the zone's data: SoilGrids / INTA soil, the NDVI history and the last month's weather."""
        report_id = report.id
        image_bytes, mime_type, image_id = await self._load_image(actor, report, image_identifier)

        context_lines, _ = await self._field_context(actor, report.field_id)
        prompt = "Identificá el tipo de suelo aparente y la porosidad/drenaje a partir de la foto de la muestra."
        if context_lines:
            prompt += "\n\nContexto del lote:\n" + "\n".join(f"- {line}" for line in context_lines)

        analysis = await self._analysis_context(actor, report, "soil")
        result, research = await self._structured(
            actor,
            parts=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type)],
            prompt=prompt,
            schema=SoilRecognitionResult,
            instruction=SOIL_SYSTEM_INSTRUCTION,
            knowledge="",
            analysis=analysis,
            deep=False,  # the soil read is the photo plus the zone's data; no web pass
            notable=lambda _r: False,
            findings=lambda _r: [],
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
                    "research": research,
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
                system_instruction=localize(HARVEST_VERDICT_INSTRUCTION, actor.country),
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
        data = latest.raw_analysis_data or {}
        periodic = data.get("llm_structured_periodic") or {}
        if not periodic and crop_cycle_id:
            periodic = crop_entry(data.get("llm_structured_zone") or {}, crop_cycle_id) or {}
        return {
            "source": "latest_periodic_report",
            "report_date": latest.created_at.date().isoformat(),
            "ready": periodic.get("harvest_ready", False),
            "verdict": periodic.get("harvest_verdict", "Sin veredicto de cosecha en el último reporte."),
        }
