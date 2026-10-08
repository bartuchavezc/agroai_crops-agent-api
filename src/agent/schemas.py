"""
Structured outputs produced by Gemini (response_schema) and returned by the agent API.
DiagnosisResult matches the `llm_structured_diagnosis` shape the web result page renders.
"""
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
    zone_data_interpretation: str = Field(
        default="",
        description="What the zone-level data given with the photo (pH, organic carbon, nitrogen and CEC estimates, "
        "INTA soil map, NDVI history, last month's weather) say about this soil, and where they agree or disagree with "
        "the photo. Always worded as regional estimates, never as measurements of this sample. Empty if no data came.",
    )
    amendment_suggestions: list[str] = Field(
        default_factory=list,
        description="Concrete soil-management suggestions with their reason (organic matter, cover crops, liming or "
        "sulfur only if the pH data call for it...). No product doses: a lab analysis gives the real numbers.",
    )


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


class PlanPoint(BaseModel):
    """A point on the plan, in meters, in the photo's frame: x to the right of the photo, y forward (away from the
    camera). The camera itself is at (0, 0)."""

    x: float = 0.0
    y: float = 0.0

    # Same tolerance as PlanElement below: a null or unparseable coordinate must not discard the whole plan.
    @field_validator("x", "y", mode="before")
    @classmethod
    def _bad_coord(cls, v):
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0


class PlanElement(BaseModel):
    """One thing around the plot, as it would be drawn on a top-down plan (a real footprint, in meters)."""

    label: str = Field(default="", description="Short name in Spanish, e.g. 'Pared del fondo', 'Pileta', 'Pino'")
    type: Literal["pared", "cerco", "arbol", "estructura", "pileta", "cantero", "otro"] = "otro"
    kind: Literal["polygon", "polyline", "circle"] = Field(
        default="polygon",
        description="polygon: closed footprint (pool, planter, building); polyline: a wall or hedge, drawn as a "
        "line with thickness_m; circle: a tree crown (center + radius_m)",
    )
    points: Optional[list[PlanPoint]] = Field(
        default=None,
        description="polygon: its corners in order (at least 3); polyline: points along the wall/hedge (at least 2). "
        "Omit for circle.",
    )
    center: Optional[PlanPoint] = Field(default=None, description="circle only: the trunk position")
    radius_m: Optional[float] = Field(default=None, description="circle only: crown radius in meters")
    thickness_m: Optional[float] = Field(default=None, description="polyline only: width in meters")
    height_m: float = Field(default=0.0, description="Height in meters (0 for flat things such as a pool)")
    confidence: float = Field(default=0.5, description="0 to 1")

    # No range constraints here: one out-of-range number must not discard the whole plan. The conversion clamps.
    # Every one of these is a real failure seen in production ("Gemini request failed: ValidationError"
    # repeating on retry too, since a schema miss is systematic for a given photo, not a one-off fluke):
    # label missing, an unrecognized kind (e.g. "rectangulo", "linea" instead of our 3 options), or a
    # non-numeric radius/thickness (e.g. "2m" with the unit attached). Each now degrades to something
    # plan_to_layout_objects already knows how to handle, instead of discarding the whole photo's plan.
    @field_validator("label", mode="before")
    @classmethod
    def _null_label(cls, v):
        return v if isinstance(v, str) else ""

    @field_validator("type", mode="before")
    @classmethod
    def _unknown_type(cls, v):
        allowed = {"pared", "cerco", "arbol", "estructura", "pileta", "cantero", "otro"}
        return v if v in allowed else "otro"

    @field_validator("kind", mode="before")
    @classmethod
    def _unknown_kind(cls, v):
        allowed = {"polygon", "polyline", "circle"}
        return v if v in allowed else "polygon"

    @field_validator("points", mode="before")
    @classmethod
    def _bad_points(cls, v):
        return v if isinstance(v, list) else None

    @field_validator("center", mode="before")
    @classmethod
    def _bad_center(cls, v):
        return v if v is None or isinstance(v, (dict, PlanPoint)) else None

    @field_validator("radius_m", "thickness_m", mode="before")
    @classmethod
    def _bad_optional_number(cls, v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @field_validator("height_m", "confidence", mode="before")
    @classmethod
    def _null_number(cls, v):
        if v is None:
            return 0.0
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    @field_validator("confidence", mode="after")
    @classmethod
    def _clamp_confidence(cls, v):
        return max(0.0, min(1.0, v))


class PlanExtraction(BaseModel):
    """The whole answer: the plan's elements. No prose."""

    elements: list[PlanElement] = Field(default_factory=list)


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


class UsageInfo(BaseModel):
    """Tokens the turn consumed across all its model calls (absent when the provider reported none)."""
    llm_calls: int
    prompt_tokens: int
    cached_tokens: int
    output_tokens: int
    thinking_tokens: int


class ChatMetadata(BaseModel):
    conversation_id: UUID
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    search_performed: bool = False
    model: str
    usage: Optional[UsageInfo] = None


class ChatResponse(BaseModel):
    response: str
    sources: list[Source] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: ChatMetadata
