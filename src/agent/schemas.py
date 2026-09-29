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


class ImagePoint(BaseModel):
    x: float = Field(ge=0, le=1, description="0 = left edge of the photo, 1 = right edge")
    y: float = Field(ge=0, le=1, description="0 = top edge of the photo, 1 = bottom edge")


class SceneElementGuess(BaseModel):
    """One thing around the plot, described in IMAGE coordinates only — meters are computed from the geometry
    afterwards (a photo gives no reliable metric depth, so the model is never asked for distances)."""

    label: str
    type: Literal["pared", "cerco", "arbol", "estructura", "pileta", "cantero", "otro"]
    kind: Literal["polygon", "polyline", "circle"] = Field(
        description="polygon: closed footprint (pool, planter, building); polyline: a wall or hedge, traced along "
        "its base; circle: a tree, a single point at the base of its trunk"
    )
    ground_points: list[ImagePoint] = Field(
        description="Where the element touches the GROUND in the photo. polygon: its corners in order (at least 3); "
        "polyline: points along the base of the wall/hedge, left to right (at least 2); circle: exactly one, the "
        "base of the trunk. Estimate hidden parts sensibly."
    )
    top_y: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Image row (0 top .. 1 bottom) of the element's top edge, straight above its FIRST ground point. "
        "Null for flat things (pool, lawn) or if the top is not visible.",
    )
    crown_width: Optional[float] = Field(
        default=None, ge=0, le=1, description="Trees only: canopy width as a fraction of the photo's width"
    )
    estimated_height_m: float = Field(ge=0, le=100, description="Rough height in meters, judged from context")
    confidence: float = Field(ge=0, le=1)


class ReferenceMatch(BaseModel):
    """The user's own measurement of ONE element in the photo, matched to the detected list."""

    object_index: int = Field(ge=0, description="0-based index into `elements` of the element the user measured")
    distance_m: Optional[float] = Field(default=None, ge=0, le=200, description="Stated distance from the camera")
    height_m: Optional[float] = Field(default=None, ge=0, le=100, description="Stated height")


class PhotoSceneExtraction(BaseModel):
    scene_description: str = Field(
        description="What is actually visible in the photo BEFORE listing elements — facts, not a verdict."
    )
    horizon_y: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Image row (0 top .. 1 bottom) of the true horizon line, if it can be judged (where far flat "
        "ground meets the sky level). Null if it cannot.",
    )
    elements: list[SceneElementGuess] = Field(default_factory=list)
    reference: Optional[ReferenceMatch] = Field(
        default=None,
        description="Only when the user supplied a reference note: which detected element it refers to and the "
        "distance/height they stated, in meters. Null if there is no note or it matches nothing in `elements`.",
    )


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
