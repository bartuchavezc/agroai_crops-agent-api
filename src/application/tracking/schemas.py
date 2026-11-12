"""What a lot's tracking plan holds. The planner (an agent) fills it following a structure, not a template: stages
with estimated windows, key moments, and items in four sections — checks and measurements, nutrition and watering,
pests and diseases, physical protection — each with its why and its how. Every change leaves a readable reason."""
import re
import uuid
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

StageStatus = Literal["pendiente", "actual", "cumplida"]
Section = Literal["revision", "nutricion_riego", "sanidad", "proteccion"]
Method = Literal["foto", "descripcion", "medicion", "inspeccion", "accion"]
Measurement = Literal[
    "ph_suelo", "ph_agua", "ce_agua", "humedad_suelo", "muestra_suelo", "temperatura", "calibre", "conteo", "otro",
]
ItemStatus = Literal["pendiente", "pedido", "respondido", "hecho", "descartado"]
OPEN_ITEM_STATUSES = ("pendiente", "pedido", "respondido")
SECTION_LABELS = {"revision": "Revisiones y mediciones", "nutricion_riego": "Nutrición y riego",
                  "sanidad": "Plagas y enfermedades", "proteccion": "Manejo físico y protección"}


class PlanStage(BaseModel):
    key: str = Field(max_length=40, description="germinacion, vegetativo, floracion, cuajado, llenado, cosecha...")
    name: str = Field(max_length=80)
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    status: StageStatus = "pendiente"
    signs: Optional[str] = Field(default=None, max_length=300, description="What shows it has started")
    risks: list[str] = Field(default_factory=list, description="What can go wrong in this stage")


class KeyMoment(BaseModel):
    key: str = Field(max_length=40)
    name: str = Field(max_length=80)
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    why: Optional[str] = Field(default=None, max_length=300)


class PlanItem(BaseModel):
    """A check the agent will make or ask for: never a chore with a fixed date."""
    id: str = Field(default="", max_length=12)
    section: Section
    title: str = Field(max_length=120)
    stage: Optional[str] = Field(default=None, description="Stage key it belongs to")
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    why: str = Field(max_length=400, description="The reason, with numbers when there are (GDD, risk index, ET)")
    how: str = Field(max_length=400, description="Exactly what to look at or measure, and with what")
    method: Method = "foto"
    measurement: Optional[Measurement] = None
    requires_tool: Optional[str] = Field(default=None, description="A growing-context tool it needs, if any")
    alternative: Optional[str] = Field(default=None, max_length=300, description="Without that tool, how instead")
    ask_user: bool = Field(default=True, description="False: the agent answers it itself (weather, models)")
    status: ItemStatus = "pendiente"
    result: Optional[str] = Field(default=None, max_length=1000)
    followup_id: Optional[UUID] = None
    updated_at: Optional[datetime] = None


class TrackingPlanContent(BaseModel):
    summary: str = Field(max_length=600, description="Two or three lines: the crop, where, how, what matters most")
    current_stage: Optional[str] = None
    stages: list[PlanStage] = Field(default_factory=list)
    key_moments: list[KeyMoment] = Field(default_factory=list)
    items: list[PlanItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, description="What it assumed (soil, watering, dates)")
    missing_context: list[str] = Field(default_factory=list, description="What it would ask to plan better")

    @model_validator(mode="after")
    def _ids(self):
        seen: set[str] = set()
        for item in self.items:
            if not item.id or item.id in seen:
                item.id = new_item_id()
            seen.add(item.id)
        return self


def new_item_id() -> str:
    return uuid.uuid4().hex[:8]


class PlanRevision(BaseModel):
    at: datetime
    by: Literal["agent", "person", "system"] = "agent"
    reason: str = Field(max_length=600, description="Readable, with numbers: «+14 % de GDD acumulado»")
    changes: list[str] = Field(default_factory=list)
    observation: Optional[str] = Field(default=None, description="What corrected it: a report, an event, an answer")


class TrackingPlanRead(BaseModel):
    id: UUID
    lot_id: UUID
    version: int
    content: TrackingPlanContent
    revisions: list[PlanRevision]
    last_observation_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class StageChange(BaseModel):
    key: str
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    status: Optional[StageStatus] = None


class ItemChange(BaseModel):
    id: str
    status: Optional[ItemStatus] = None
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    result: Optional[str] = Field(default=None, max_length=1000)
    followup_id: Optional[UUID] = None


class PlanRevise(BaseModel):
    """A correction: what moved and why. Unset fields stay as they were."""
    reason: str = Field(min_length=3, max_length=600)
    observation: Optional[str] = None
    current_stage: Optional[str] = None
    stages: list[StageChange] = Field(default_factory=list)
    items: list[ItemChange] = Field(default_factory=list)
    new_items: list[PlanItem] = Field(default_factory=list)
    key_moments: Optional[list[KeyMoment]] = None
    missing_context: Optional[list[str]] = None


_SPACES = re.compile(r"\s+")


def clean(text: str) -> str:
    return _SPACES.sub(" ", text or "").strip()
