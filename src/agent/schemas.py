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


class Source(BaseModel):
    title: Optional[str] = None
    uri: str


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
    metadata: ChatMetadata
