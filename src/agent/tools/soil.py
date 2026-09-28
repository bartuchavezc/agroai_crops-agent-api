"""Soil-sample photo recognition tool: persists what the agent already analyzed in this turn (same
pattern as save_diagnosis_report in knowledge.py) — apparent type/porosity only, never nutrient levels."""
from typing import Optional

from src.application.reports.schemas import ReportCreate
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, resolve_field, tool


def soil_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def save_soil_sample(
        apparent_soil_type: str,
        apparent_porosity: str,
        visual_evidence: str,
        drainage_note: str,
        confidence: float,
        companion_planting_suggestions: Optional[list[str]] = None,
        field: Optional[str] = None,
    ) -> dict:
        """Persist your analysis of a soil-sample photo sent in this message (after you analyzed it).
        apparent_soil_type: arenoso|arcilloso|franco|franco-arenoso|franco-arcilloso|orgánico|desconocido.
        apparent_porosity: alta|media|baja. visual_evidence: texture/color/cohesion facts seen in the photo
        BEFORE classifying. confidence: 0-0.6 max — this is a photo of a small sample, never a lab test,
        and must never claim nitrogen/nutrient levels (that always requires a real lab analysis)."""
        if not ctx.image_identifier:
            raise InvalidInputError("There is no photo in this message; soil samples need a photo.")
        field_id = (await resolve_field(deps, ctx, field)).id if (field or ctx.default_field_id) else None
        confidence = min(confidence, 0.6)
        soil = {
            "apparent_soil_type": apparent_soil_type,
            "apparent_porosity": apparent_porosity,
            "visual_evidence": visual_evidence,
            "drainage_note": drainage_note,
            "companion_planting_suggestions": companion_planting_suggestions or [],
            "confidence": confidence,
            "explicit_limitations": (
                "Esta clasificación es visual, a partir de una foto de una muestra chica: no determina "
                "nitrógeno ni ningún nutriente, eso requiere un análisis de laboratorio real."
            ),
            "needs_human_expert": confidence < 0.4,
        }
        report = await deps.reports.create_report(
            ctx.actor,
            ReportCreate(
                title="Muestra de suelo",
                summary=f"{apparent_soil_type}, porosidad {apparent_porosity}",
                recommendations="\n".join(companion_planting_suggestions or []),
                image_identifier=ctx.image_identifier,
                status="ANALYSIS_COMPLETED",
                report_type="soil",
                field_id=field_id,
                raw_analysis_data={
                    "llm_structured_soil": soil,
                    "analyzed_image_identifier": ctx.image_identifier,
                    "source": "chat",
                },
            ),
        )
        return {"report_id": str(report.id), "soil": compact(soil)}

    return [save_soil_sample]
