"""
Multimodal crop analysis: the photo goes straight to Gemini together with the field/cycle context.
Two report types share this service:
- "diagnosis": disease/pest/nutrition focused, single photo, no cycle history (DiagnosisResult).
- "periodic": routine tracking (health/growth/stress/harvest/objectives/risks), grounded in the crop
  cycle's timeline and event log (PeriodicReportResult). A periodic report of a zone (cajón, cantero,
  invernadero, hidroponía) covers every active crop of the zone at once, from 1-3 photos
  (ZonePeriodicReportResult, stored as llm_structured_zone).
"""
import asyncio
import logging
import time
from dataclasses import replace
from typing import Optional
from uuid import UUID

from google.genai import types

from src.application.alerts.rules_engine import RulesEngine
from src.application.farm.service import FarmService
from src.application.followups.schemas import FollowUpCreate
from src.application.notifications.service import NotificationService
from src.application.reports.schemas import Report, ReportUpdate
from src.application.reports.service import ReportsService
from src.application.storage.service import StorageService
from src.auth.services.profile_service import ProfileService
from src.providers.weather.service import WeatherService
from src.shared.domain.actor import Actor
from src.shared.domain.locale import localized, today_in
from src.shared.utils.errors import InvalidInputError, ProviderError
from src.shared.utils.trace import set_trace_id

from ..prompts.analysis import ANALYSIS_GROUNDING, DEEP_REFINE_INSTRUCTION
from ..prompts.diagnosis import SYSTEM_INSTRUCTION
from ..prompts.harvest import HARVEST_VERDICT_INSTRUCTION, PLANT_COUNT_INSTRUCTION
from ..prompts.knowledge import modules_for
from ..prompts.periodic import (
    FOLLOWUP_SYSTEM_INSTRUCTION,
    PERIODIC_SYSTEM_INSTRUCTION,
    ZONE_GROUP_SYSTEM_INSTRUCTION,
    ZONE_OVERVIEW_SYSTEM_INSTRUCTION,
    ZONE_SYNTHESIS_SYSTEM_INSTRUCTION,
)
from ..prompts.soil import SOIL_SYSTEM_INSTRUCTION
from ..prompts.voice import localize
from ..providers.gemini import GeminiGateway, patient_calls
from ..schemas import DiagnosisResult, HarvestVerdictResult, PlantCountResult, SoilRecognitionResult
from ..usage import TurnUsage
from .analysis_context import AnalysisContext, AnalysisContextBuilder, to_json
from .periodic_report import (
    FollowUpPassResult,
    PeriodicReportResult,
    ZoneGroupAssessment,
    ZoneOverviewResult,
    ZoneSynthesisResult,
    crop_entry,
    format_cycle_progress,
    format_event_history,
)
from .zone_grouping import CropGroup, group_cycles, merge_zone_result
from .zone_followups import (
    EVOLUTION_LABEL,
    OPEN_SEVERITIES,
    PREVIOUS_PHOTO_SIDE,
    FollowUpInput,
    evaluation_notes,
    followup_input,
    followup_pass_contents,
    issue_photo,
    new_issues,
    open_followup_lines,
    proposes_close,
)
from .zone_photos import followup_photos, group_parts, overview_parts, photo_count, zone_photos
from .zone_task_loop import ZoneTask, run_zone_tasks

logger = logging.getLogger(__name__)

# An outer safety net on the whole fanned-out zone analysis (overview + one call per crop group + synthesis,
# run one at a time — see zone_task_loop.py): generous, since this is now several sequential calls, each with
# its own 2-attempt retry and 3-model fallback chain, plus the per-minute quota waits of a background job (see
# gemini.py's patient_calls: usually well under a minute per call). It starts once the job's turn in its API
# key's queue comes (GeminiGateway.serialized), not while it waits behind another analysis. A timeout here
# lands in analyze()'s existing except-mark-ANALYSIS_FAILED path exactly like any other error.
ZONE_ANALYSIS_TIMEOUT_SECONDS = 600


async def analyze_in_background(
    diagnosis_service: "DiagnosisService", actor: Actor, report_id: UUID,
    image_identifier: Optional[str] = None, deep: Optional[bool] = None,
) -> None:
    """Never let a background-task failure surface as an unhandled exception — there's no caller here to
    return it to. `analyze()` already persists ANALYSIS_FAILED on any error, so the UI can show a
    "Reintentar" button instead of the report staying stuck at "Analizando..." forever. Shared by the
    upload endpoints (`src/application/storage/router.py`) and the `/analyze` retry endpoint (`router.py`
    in this package) so both background the exact same way, instead of one reaching into the other."""
    try:
        # Queued per API key, and nobody waits on the response: per-minute quotas are waited out, not failed on.
        async with diagnosis_service.gemini.serialized(actor.user_id):
            with patient_calls():
                await diagnosis_service.analyze(actor, report_id, image_identifier, deep)
    except Exception:  # noqa: BLE001 - background task, nothing to return the error to
        logger.exception(f"Background analysis failed for report {report_id}")


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
        followup_service=None,
    ):
        self.gemini = gemini
        self.followups = followup_service  # FollowUpService: what the zone analysis follows and writes down
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
            if overview.field.id == field_id and overview.active_lots:
                crops = ", ".join(
                    f"{localized(c.crop_name, c.crop_i18n, actor.locale)}"
                    f"{' ' + c.variety if c.variety else ''} ({c.status})"
                    for c in overview.active_lots
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
        self, actor: Actor, field_id: Optional[UUID], lot_id: Optional[UUID]
    ) -> list[str]:
        lines: list[str] = []
        if not lot_id:
            return lines
        cycle = await self.farm.get_lot(actor, lot_id)
        crop_master = await self.farm.get_crop_master(actor, cycle.crop_master_id) if cycle.crop_master_id else None
        lines.append(format_cycle_progress(cycle, crop_master, today_in(actor.timezone)))

        events = await self.farm.list_events(actor, lot_id=lot_id, limit=50)
        if events:
            lines.append("Historial de eventos del ciclo (decisiones/manejo registrado):")
            lines.extend(f"- {line}" for line in format_event_history(events))
        else:
            lines.append("No hay eventos registrados para este ciclo todavía.")

        previous = await self.reports.list_reports(
            actor, lot_id=lot_id, report_type="periodic", limit=3
        )
        previous = [r for r in previous if r.status == "ANALYSIS_COMPLETED"]
        if previous:
            lines.append("Análisis periódicos previos de este mismo ciclo (más reciente primero):")
            for r in previous:
                entry = crop_entry((r.raw_analysis_data or {}).get("llm_structured_zone") or {}, lot_id)
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
        cycles = overview[0].active_lots if overview else []
        ids = set(getattr(report, "lot_ids", None) or [])
        if report.lot_id:
            ids.add(report.lot_id)
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
        analysis: AnalysisContext, deep: Optional[bool], notable, findings, usage_sink: Optional[TurnUsage] = None,
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
            actor.user_id, contents=[*parts, prompt], schema=schema, system_instruction=system,
            thinking_level="medium", usage_sink=usage_sink,
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
                    thinking_level="high", usage_sink=usage_sink,
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
        # The report id is a more useful grep key than the generic per-HTTP-request id the middleware set
        # (main.py) — it's the one id that's the same whether this runs synchronously in the request or
        # later via BackgroundTasks (the retry path), and it's already in every persisted report.
        set_trace_id(str(report_id))
        report = await self.reports.get_report(actor, report_id)
        try:
            if report.report_type == "periodic" and report.zone_id and report.lot_id is None:
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
        context_lines += await self._periodic_context(actor, report.field_id, report.lot_id)

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

    async def _zone_shared_context(self, actor: Actor, report: Report):
        """Zone-level lines every pass of the fanned-out analysis sees (small, never worth scoping): zone
        label/notes, zone-wide events, previous zone reports, field description. Returns `(zone, lines)` —
        the zone object too, since the orchestrator needs its label for the title/notification anyway."""
        zone = await self.farm.get_zone(actor, report.zone_id)
        lines = [f"Zona: {zone.label}" + (f". Notas: {zone.notes}" if zone.notes else "")]
        zone_events = [
            e for e in await self.farm.list_events(actor, field_id=report.field_id, zone_id=zone.id, limit=50)
            if len(e.lot_ids) != 1  # logged on the zone as a whole, not on one of its lots
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
        return zone, lines

    async def _zone_cycles_in_scope(self, actor: Actor, report: Report) -> list[tuple[str, str]]:
        """(cycle_id, crop_name) pairs for this zone report's cycles, in `report.lot_ids`' order —
        the grouping input. Crop names come from the account's overview (already fetched elsewhere, no
        extra round trip), falling back to "(desconocido)" for a cycle no longer in it (e.g. harvested since
        upload): that groups with other no-ficha crops rather than failing the whole analysis."""
        overview = [o for o in await self.farm.overview(actor) if o.field.id == report.field_id]
        names = {str(c.id): c.crop_name for o in overview for c in o.active_lots}
        return [(str(cid), names.get(str(cid), "(desconocido)")) for cid in report.lot_ids]

    async def _cycle_context(self, actor: Actor, cycle_id) -> list[str]:
        """Progress + up to 20 events of ONE cycle — the body of the old flattened per-cycle loop, now
        returned per-cycle so a group task only gets the cycles it is actually responsible for."""
        cycle = await self.farm.get_lot(actor, cycle_id)
        crop_master = await self.farm.get_crop_master(actor, cycle.crop_master_id)
        lines = [
            f"Ciclo lot_id={cycle.id}:",
            format_cycle_progress(cycle, crop_master, today_in(actor.timezone)),
        ]
        events = await self.farm.list_events(actor, lot_id=cycle.id, limit=20)
        if events:
            lines.append("Eventos del ciclo: " + "; ".join(format_event_history(events)))
        return lines

    async def _zone_overview_pass(
        self, actor: Actor, parts: list, zone_lines: list[str], cycle_pairs: list[tuple[str, str]],
        notes_lines: list[str], usage_sink: Optional[TurnUsage] = None,
    ) -> ZoneOverviewResult:
        """The whole-zone read, not narrowed to one crop group — no fichas, cheap. `parts` are the general shots
        (every photo when the report has no photo roles: see zone_photos.py)."""
        registered = ", ".join(dict.fromkeys(name for _, name in cycle_pairs)) or "(ninguno)"
        lines = [*zone_lines, f"Cultivos registrados en esta zona: {registered}", *notes_lines]
        prompt = (
            f"Mirá las {photo_count(parts)} foto/s de la zona completa y dame una lectura visual de conjunto.\n\n"
            "Contexto:\n" + "\n".join(f"- {line}" for line in lines)
        )
        return await self.gemini.generate_structured(
            actor.user_id, contents=[*parts, prompt], schema=ZoneOverviewResult,
            system_instruction=localize(ZONE_OVERVIEW_SYSTEM_INSTRUCTION, actor.country), thinking_level="medium",
            usage_sink=usage_sink,
        )

    async def _zone_group_pass(
        self, actor: Actor, parts: list, group: CropGroup, cycle_lines: dict[str, list[str]],
        zone_lines: list[str], field_data_lines: list[str], knowledge: str, notes_lines: list[str], *, recheck: bool,
        usage_sink: Optional[TurnUsage] = None,
    ) -> tuple[ZoneGroupAssessment, list[str]]:
        """One group's worth of crops, with only ITS fichas and ITS cycles — this is the call that used to
        carry every crop of the zone at once. Returns `(result, loaded_reference_names)` for the caller to
        fold into the persisted `research` summary. Always `deep=False`: the web-research refine pass stays
        out of scope for a fanned-out zone analysis (see the plan) — it would multiply N calls by 2."""
        text, loaded = self.analysis_context.references_for(
            self.analysis_context.crop_reference_names(group.crop_names)
        )
        analysis = AnalysisContext(
            references=text, loaded=loaded, data_lines=field_data_lines, crops=list(group.crop_names)
        )
        own_cycle_lines = [line for cid in group.cycle_ids for line in cycle_lines[cid]]
        lines = [*zone_lines, *own_cycle_lines, *notes_lines]
        intro = (
            "Revisá con más detalle este grupo de cultivos: mostró señales de riesgo en una primera pasada."
            if recheck else "Hacé el seguimiento de este grupo de cultivos de la zona."
        )
        prompt = f"{intro}\n\nContexto de la zona y de estos ciclos:\n" + "\n".join(f"- {line}" for line in lines)
        result, _research = await self._structured(
            actor, parts=parts, prompt=prompt, schema=ZoneGroupAssessment, instruction=ZONE_GROUP_SYSTEM_INSTRUCTION,
            knowledge=knowledge, analysis=analysis, deep=False,
            notable=lambda _r: False, findings=lambda _r: [], usage_sink=usage_sink,
        )
        return result, loaded

    async def _zone_synthesis_pass(
        self, actor: Actor, tasks: list["ZoneTask"], zone_lines: list[str], notes_lines: list[str],
        usage_sink: Optional[TurnUsage] = None,
    ) -> ZoneSynthesisResult:
        """Text-only, cheap: reasons over the overview + every group's notes, never the photos or fichas
        again. Runs last by construction (zone_task_loop.py never makes it "ready" until everything else is
        terminal), so every task it looks at here is already done or failed."""
        overview = next((t.result for t in tasks if t.kind == "overview" and t.status == "done"), None)
        overview_lines = [f"Lectura visual de conjunto: {overview.zone_observations}"] if overview else []
        group_lines = []
        for t in tasks:
            if t.kind in ("group", "recheck") and t.status == "done":
                names = ", ".join(t.payload["group"].crop_names)
                r: ZoneGroupAssessment = t.result
                extra = f" Recomendaciones: {'; '.join(r.group_recommendations)}." if r.group_recommendations else ""
                group_lines.append(f"Grupo {names}: riesgo {r.group_risk_severity}. {r.group_notes}{extra}")
            if t.kind == "followup" and t.status == "done":
                group_lines += [
                    f"Seguimiento id={e.followup_id}: {EVOLUTION_LABEL[e.evolution]}. {e.evidence}"
                    for e in t.result.evaluations
                ]
        lines = [*zone_lines, *overview_lines, *group_lines, *notes_lines]
        prompt = (
            "Con la lectura de conjunto y la evaluación de cada grupo de cultivos de abajo, cerrá el "
            "seguimiento de la zona.\n\nContexto:\n" + "\n".join(f"- {line}" for line in lines)
        )
        return await self.gemini.generate_structured(
            actor.user_id, contents=[prompt], schema=ZoneSynthesisResult,
            system_instruction=localize(ZONE_SYNTHESIS_SYSTEM_INSTRUCTION, actor.country), thinking_level="medium",
            usage_sink=usage_sink,
        )

    async def _open_followups(self, actor: Actor, zone_id) -> list:
        if self.followups is None:
            return []
        return await self.followups.list_followups(actor, zone_id=zone_id, status="abierto")

    async def _followup_inputs(
        self, actor: Actor, photos: list, open_followups: list, current_images: set[str]
    ) -> list[FollowUpInput]:
        """The open follow-ups photographed this time, each with its history and its ANTES photo loaded (at a
        lower resolution: it is only the reference). A follow-up whose last photo can't be loaded is compared
        against its history alone."""
        by_id = {str(f.id): f for f in open_followups}
        inputs = []
        for followup_id, shots in followup_photos(photos).items():
            followup = by_id.get(followup_id)
            if followup is None:
                continue
            detail = await self.followups.get(actor, followup.id)
            item = followup_input(followup, shots, detail.events, current_images)
            if item.previous_photo:
                try:
                    data, mime = await self.storage.get_image_for_model(
                        actor, item.previous_photo, PREVIOUS_PHOTO_SIDE
                    )
                    item.previous_part = types.Part.from_bytes(data=data, mime_type=mime)
                except Exception:  # noqa: BLE001 - compare against the history instead
                    logger.warning(f"Follow-up {followup_id}: previous photo {item.previous_photo} not loadable")
            inputs.append(item)
        return inputs

    async def _apply_followups(
        self, actor: Actor, report: Report, image_ids: list[str], cycle_ids: list[str], open_followups: list,
        inputs: list[FollowUpInput], evaluations: list, issues: list,
    ) -> dict:
        """Writes down what the analysis found about follow-ups — each evaluation and each new problem become
        bitácora entries with their evidence, by the agent — and what it proposes the person do. Never fails the
        analysis: what couldn't be written is logged and left out. Idempotent per report (a retry of the same
        report doesn't write twice)."""
        found: dict = {"evaluations": [], "opened": [], "suggested_actions": []}
        if self.followups is None:
            return found
        agent = replace(actor, via="agent")
        by_id = {str(i.followup.id): i for i in inputs}
        for evaluation in evaluations:
            item = by_id.get(evaluation.followup_id)
            if item is None:
                continue
            followup = item.followup
            new_photos = [image_ids[p.number - 1] for p in item.photos]
            entry = {
                "followup_id": evaluation.followup_id, "title": followup.title, "evolution": evaluation.evolution,
                "evidence": evaluation.evidence, "confidence": evaluation.confidence,
                "photo": new_photos[0] if new_photos else None, "previous_photo": item.previous_photo,
                "previous_at": item.previous_at.isoformat() if item.previous_at else None,
            }
            already = any(
                ev.kind == "report" and ev.identifier == str(report.id) for e in item.history for ev in e.evidence
            )
            if not already:
                evidence = [{"kind": "photo", "identifier": i} for i in new_photos]
                if item.previous_photo:
                    evidence.append({
                        "kind": "photo", "identifier": item.previous_photo,
                        "note": f"antes ({item.previous_at.date().isoformat()})" if item.previous_at else "antes",
                    })
                try:
                    await self.followups.write_entry(
                        agent, followup, evaluation_notes(followup, evaluation),
                        {"followup_action": "evaluated", "evolution": evaluation.evolution,
                         "confidence": evaluation.confidence},
                        evidence, report.id,
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(f"Could not log the evaluation of follow-up {followup.id}")
            found["evaluations"].append(entry)
            if proposes_close(evaluation, item.previous_evaluations):
                found["suggested_actions"].append({
                    "type": "close_followup", "followup_id": evaluation.followup_id, "title": followup.title,
                    "reason": "No se vio en dos seguimientos seguidos.",
                })
            elif evaluation.evolution == "peor":
                found["suggested_actions"].append({
                    "type": "treat_followup", "followup_id": evaluation.followup_id, "title": followup.title,
                    "reason": evaluation.evidence,
                })

        followed = {str(f.id) for f in open_followups}
        opened_by_report = {
            f.title.strip().lower(): f
            for f in await self.followups.list_followups(actor, zone_id=report.zone_id)
            if f.origin_report_id == report.id
        }
        for issue in new_issues(issues, followed, set(cycle_ids)):
            photo = issue_photo(issue, image_ids)
            if issue.severity not in OPEN_SEVERITIES:
                found["suggested_actions"].append({
                    "type": "open_followup", "title": issue.title, "kind": issue.kind, "severity": issue.severity,
                    "lot_ids": issue.lot_ids, "photo_hint": issue.photo_hint, "notes": issue.what_was_seen,
                    "photo": photo,
                })
                continue
            existing = opened_by_report.get(issue.title.strip().lower())
            try:
                followup = existing or await self.followups.create(agent, FollowUpCreate(
                    field_id=report.field_id, zone_id=report.zone_id, lot_ids=issue.lot_ids, title=issue.title,
                    kind=issue.kind, severity=issue.severity, photo_hint=issue.photo_hint,
                    notes=issue.what_was_seen, origin_report_id=report.id,
                    evidence=[{"kind": "photo", "identifier": photo}] if photo else [],
                ))
            except Exception:  # noqa: BLE001
                logger.exception(f"Could not open a follow-up for {issue.title!r}")
                continue
            found["opened"].append({"followup_id": str(followup.id), "title": followup.title,
                                    "severity": followup.severity})
        return found

    async def _analyze_zone(self, actor: Actor, report: Report, deep: Optional[bool] = None) -> dict:
        """Daily tracking of a whole zone, fanned out: one whole-photo overview, one Gemini call per crop
        group (crops sharing a ficha técnica — see zone_grouping.py), and one text-only synthesis — run by
        the "until done" task queue in zone_task_loop.py, not a fixed sequence. This replaces the single call
        that used to carry every active crop's ficha técnica at once (the design that blew a 10-crop zone's
        token budget). `deep` is accepted for signature parity with analyze()'s other branches but unused:
        the web-research refine pass is out of scope for the fanned-out calls (see the plan)."""
        image_ids = report.image_identifiers or ([report.image_identifier] if report.image_identifier else [])
        if not image_ids:
            raise InvalidInputError("The report has no image to analyze.")
        parts = []
        for image_id in image_ids:
            data, mime_type = await self.storage.get_image_for_model(actor, image_id, self.max_image_side)
            parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))

        field_lines, weather = await self._field_context(actor, report.field_id)
        zone, zone_lines = await self._zone_shared_context(actor, report)
        cycle_pairs = await self._zone_cycles_in_scope(actor, report)
        if not cycle_pairs:
            zone_lines.append("La zona no tiene ciclos de cultivo activos registrados.")
        cycle_ids = [cid for cid, _ in cycle_pairs]

        field = None
        if report.field_id:
            try:
                field = await self.farm.get_field(actor, report.field_id)
            except Exception:  # noqa: BLE001 - the analysis still runs on the photo and the basic context
                logger.exception("Zone analysis field lookup failed; continuing without field-level data")
        field_data_lines = await self.analysis_context.field_data_lines(actor, report, field) if field else []

        profile = await self.profiles.get_profile_context(actor.user_id)
        crop_families = await self.farm.crop_families(actor)
        field_texts = [line for line in field_lines if "Suelo:" in line]
        knowledge = modules_for(
            actor.country, profile.calculated_profile if profile else None, crop_families, field_texts
        )
        notes_lines = [f"Nota del usuario: {report.notes}"] if report.notes else []

        groups = group_cycles(cycle_pairs)
        cycle_lines = {cid: await self._cycle_context(actor, cid) for cid in cycle_ids}
        loaded_by_task: dict[str, list[str]] = {}
        usage = TurnUsage()

        crop_by_cycle = dict(cycle_pairs)
        photos = zone_photos(parts, report.photo_roles)
        open_followups = await self._open_followups(actor, zone.id)
        zone_lines += open_followup_lines(open_followups)
        followup_inputs = await self._followup_inputs(actor, photos, open_followups, set(image_ids))

        tasks: list[ZoneTask] = [ZoneTask(id="overview", kind="overview")]
        tasks += [ZoneTask(id=f"group:{g.id}", kind="group", payload={"group": g}) for g in groups]
        if followup_inputs:
            tasks.append(ZoneTask(id="followup", kind="followup"))
        tasks.append(ZoneTask(id="synthesis", kind="synthesis"))

        logger.info(
            f"Zone analysis starting report={report.id} zone={report.zone_id} cycles={len(cycle_ids)} "
            f"groups={[(g.id, list(g.crop_names)) for g in groups]} notes={'yes' if report.notes else 'no'}"
        )

        async def execute(task: ZoneTask):
            if task.kind == "overview":
                return await self._zone_overview_pass(
                    actor, overview_parts(photos, crop_by_cycle), zone_lines, cycle_pairs, notes_lines, usage_sink=usage
                )
            if task.kind in ("group", "recheck"):
                group = task.payload["group"]
                result, loaded = await self._zone_group_pass(
                    actor, group_parts(photos, group.cycle_ids, crop_by_cycle), group, cycle_lines, zone_lines,
                    field_data_lines, knowledge, notes_lines, recheck=task.kind == "recheck", usage_sink=usage,
                )
                loaded_by_task[task.id] = loaded
                return result
            if task.kind == "followup":
                return await self.gemini.generate_structured(
                    actor.user_id, contents=followup_pass_contents(followup_inputs), schema=FollowUpPassResult,
                    system_instruction=localize(FOLLOWUP_SYSTEM_INSTRUCTION, actor.country), thinking_level="medium",
                    usage_sink=usage,
                )
            return await self._zone_synthesis_pass(actor, tasks, zone_lines, notes_lines, usage_sink=usage)

        started = time.monotonic()
        await asyncio.wait_for(run_zone_tasks(tasks, execute), timeout=ZONE_ANALYSIS_TIMEOUT_SECONDS)
        elapsed = time.monotonic() - started

        synthesis_task = next(t for t in tasks if t.kind == "synthesis")
        group_tasks = [t for t in tasks if t.kind == "group"]
        failed_ids = [t.id for t in tasks if t.status == "failed"]
        if synthesis_task.status != "done" or (group_tasks and not any(t.status == "done" for t in group_tasks)):
            logger.error(
                f"Zone analysis failed report={report.id} elapsed={elapsed:.1f}s failed_tasks={failed_ids} "
                f"{usage.log_line(report.id, self.gemini.model)}"
            )
            raise ProviderError("No se pudo completar el seguimiento de la zona en este intento.")

        recheck_by_group = {
            t.payload["group"].id: t for t in tasks if t.kind == "recheck" and t.status == "done"
        }
        resolved_groups = [
            recheck_by_group[t.payload["group"].id].result if t.payload["group"].id in recheck_by_group else t.result
            for t in group_tasks
            if t.status == "done"
        ]
        overview_task = next(t for t in tasks if t.kind == "overview")
        overview_result = (
            overview_task.result if overview_task.status == "done"
            else ZoneOverviewResult(zone_observations="", unlisted_plants=[])
        )
        result = merge_zone_result(cycle_ids, resolved_groups, overview_result, synthesis_task.result)
        research = {"references": sorted({name for names in loaded_by_task.values() for name in names}), "deep": False}
        followup_task = next((t for t in tasks if t.kind == "followup" and t.status == "done"), None)
        followups_found = await self._apply_followups(
            actor, report, image_ids, cycle_ids, open_followups, followup_inputs,
            followup_task.result.evaluations if followup_task else [],
            [issue for g in resolved_groups for issue in g.issues],
        )

        logger.info(
            f"Zone analysis done report={report.id} elapsed={elapsed:.1f}s failed_tasks={failed_ids} "
            f"overall_health={result.overall_health} risk_severity={result.risk_severity} "
            f"confidence={result.confidence:.2f} needs_human_expert={result.needs_human_expert} "
            f"{usage.log_line(report.id, self.gemini.model)}"
        )

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
                    "followups": followups_found,
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

    async def count_plants(
        self, actor: Actor, image_identifier: str, crop_name: Optional[str] = None, expected: Optional[float] = None
    ) -> PlantCountResult:
        """How many live plants a photo shows, as a proposal for the person to confirm (nothing is saved)."""
        image_bytes, mime_type = await self.storage.get_image_for_model(actor, image_identifier, self.max_image_side)
        prompt = "Contá las plantas vivas de la foto."
        if crop_name:
            prompt += f" Cultivo: {crop_name}."
        if expected is not None:
            prompt += f" Se esperaban unas {expected:g} (no ajustes el conteo a ese número: contá lo que se ve)."
        return await self.gemini.generate_structured(
            actor.user_id,
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
            schema=PlantCountResult,
            system_instruction=localize(PLANT_COUNT_INSTRUCTION, actor.country),
        )

    async def harvest_verdict(
        self,
        actor: Actor,
        field_id: Optional[UUID],
        lot_id: Optional[UUID] = None,
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
            context_lines += await self._periodic_context(actor, field_id, lot_id)
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
            actor, field_id=field_id, lot_id=lot_id, report_type="periodic", limit=1
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
        if not periodic and lot_id:
            periodic = crop_entry(data.get("llm_structured_zone") or {}, lot_id) or {}
        return {
            "source": "latest_periodic_report",
            "report_date": latest.created_at.date().isoformat(),
            "ready": periodic.get("harvest_ready", False),
            "verdict": periodic.get("harvest_verdict", "Sin veredicto de cosecha en el último reporte."),
        }
