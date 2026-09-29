"""
Structured outputs produced by Gemini (response_schema) and returned by the agent API.
DiagnosisResult matches the `llm_structured_diagnosis` shape the web result page renders.
"""
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class Treatment(BaseModel):
    title: str
    description: str


class DiagnosisResult(BaseModel):
    detected_crop: Optional[str] = Field(None, description="Crop identified in the photo, in Spanish")
    visual_evidence: str = Field(
        description="Concrete visual evidence seen in the photo BEFORE naming a cause: color, shape and "
        "distribution of lesions/spots, which plant parts are affected, spread pattern. Facts, not a verdict."
    )
    general_diagnosis: str = Field(
        description="Main diagnosis in one or two sentences, in Spanish, explicitly justified by visual_evidence"
    )
    likely_category: Literal["disease", "pest", "nutrient_deficiency", "abiotic_stress", "healthy", "uncertain"] = (
        Field(description="Coarse classification, decided from visual_evidence before naming the exact cause")
    )
    possible_causes: list[str] = Field(
        default_factory=list,
        description="If the evidence is ambiguous between similar causes, list the plausible alternatives here "
        "too (not just the winning one) and reflect that ambiguity by lowering confidence.",
    )
    recommended_treatments: list[Treatment] = Field(default_factory=list)
    preventative_measures: list[str] = Field(default_factory=list)
    specific_recommendations: list[str] = Field(default_factory=list)
    additional_notes: str = ""
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1, description="0-1 confidence in the diagnosis")
    affected_area_percent: Optional[float] = Field(None, ge=0, le=100)
    needs_human_expert: bool = Field(description="True when an agronomist should confirm before acting")


class SoilRecognitionResult(BaseModel):
    apparent_soil_type: Literal[
        "arenoso", "arcilloso", "franco", "franco-arenoso", "franco-arcilloso", "orgánico", "desconocido"
    ]
    apparent_porosity: Literal["alta", "media", "baja"]
    visual_evidence: str = Field(description="Texture/color/cohesion facts seen in the photo BEFORE classifying")
    drainage_note: str
    companion_planting_suggestions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=0.6, description="Capped: a photo of a small soil sample, not a lab test")
    explicit_limitations: str = Field(
        description="Must always state that nitrogen/nutrient levels cannot be determined from a photo"
    )
    needs_human_expert: bool = False


class HarvestVerdictResult(BaseModel):
    ready: bool
    verdict: str = Field(description="Justification citing the concrete visual signal, in Spanish")
    confidence: float = Field(ge=0, le=1)


class SatelliteImageAnalysis(BaseModel):
    visual_pattern: str = Field(
        description="What's actually visible in the color pattern (distribution, uniformity, patches) "
        "BEFORE interpreting it — facts, not a verdict."
    )
    zone_assessment: str = Field(description="What that pattern implies for zone health, justified by visual_pattern")
    notable_areas: list[str] = Field(default_factory=list, description="Specific things worth flagging, if any")
    confidence: float = Field(ge=0, le=1)


class LayoutObjectGuess(BaseModel):
    label: str
    type: Literal["pared", "arbol", "estructura", "pileta", "cantero", "otro"]
    horizontal_position: Literal["izquierda", "centro-izquierda", "centro", "centro-derecha", "derecha"] = Field(
        description="Where it sits across the frame of the photo, left to right"
    )
    depth_position: Literal["primer_plano", "medio", "fondo"] = Field(
        description="How far from the camera it looks: close, middle or far"
    )
    estimated_height_m: float = Field(ge=0, le=100, description="Rough height in meters, judged from context")
    confidence: float = Field(ge=0, le=1)


class PhotoLayoutExtraction(BaseModel):
    scene_description: str = Field(
        description="What is actually visible in the photo BEFORE listing objects — facts, not a verdict."
    )
    objects: list[LayoutObjectGuess] = Field(default_factory=list)


class Source(BaseModel):
    title: Optional[str] = None
    uri: str


class Attachment(BaseModel):
    type: Literal["zone_map"]
    image_identifier: str
    field_id: UUID
    caption: str


class ToolCallInfo(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)
    ok: bool = True


class ChatMetadata(BaseModel):
    conversation_id: UUID
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    search_performed: bool = False
    model: str


class ChatResponse(BaseModel):
    response: str
    sources: list[Source] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: ChatMetadata
