"""How closely the agent follows a person's crops, and what the person has to work with.

Prediction always runs (the agent keeps a tracking plan per lot and simulates what it can't see); the intensity only
sets how often it asks the person for a check — a photo, a description, a measurement. It starts from the enrollment
answers and the person can change it from their profile at any time. `growing_context` is what the planner must fit:
the tools at hand, the hours a week and the money the person is willing to put in."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

TrackingIntensity = Literal["baja", "media", "alta"]
INTENSITIES: tuple[str, ...] = ("baja", "media", "alta")

# Tools the planner knows how to use for a check; anything else goes in `other_tools`.
GROWING_TOOLS = (
    "medidor_ph", "conductimetro", "tensiometro", "sensor_humedad", "termometro", "trampas_cromaticas",
    "malla_sombra", "cobertor", "riego_goteo", "temporizador_riego", "lupa", "balanza",
)
Budget = Literal["minimo", "bajo", "medio", "alto"]

# Data requests (ask) per person and week, by intensity. Urgent risks never count against it.
WEEKLY_ASKS: dict[str, int] = {"baja": 2, "media": 4, "alta": 8}


def intensity_from_form(form: Optional[dict]) -> TrackingIntensity:
    """From the enrollment: q10 (who keeps the records) sets the base — "el agente anota todo por mí" wants little
    asked of them, "control total del historial" wants close tracking — and a beginner (q1/q2 mostly A) gets one step
    more of follow-up, because that is who most needs a nudge at the right moment."""
    form = form or {}
    base = {"A": 0, "B": 1, "C": 2}.get(form.get("q10", "B"), 1)
    beginner = sum(form.get(q) == "A" for q in ("q1", "q2")) >= 2
    return INTENSITIES[min(base + (1 if beginner and base < 1 else 0), 2)]  # type: ignore[return-value]


class GrowingContext(BaseModel):
    tools: list[str] = Field(default_factory=list, description=f"Of {', '.join(GROWING_TOOLS)}")
    other_tools: Optional[str] = Field(default=None, max_length=300)
    weekly_hours: Optional[float] = Field(default=None, ge=0, le=80, description="Hours a week for the crops")
    budget: Optional[Budget] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class TrackingProfileRead(BaseModel):
    intensity: TrackingIntensity
    intensity_source: Literal["enroll", "person", "default"]
    enroll_intensity: TrackingIntensity
    weekly_asks: int
    growing_context: GrowingContext
    profile: Optional[str] = None


class TrackingProfileUpdate(BaseModel):
    intensity: Optional[TrackingIntensity] = None
    reset_intensity: bool = Field(default=False, description="Back to what the enrollment suggests")
    growing_context: Optional[GrowingContext] = None


def tracking_profile_read(profile) -> TrackingProfileRead:
    """`profile`: a UserProfile row or None (not enrolled yet)."""
    form = getattr(profile, "form", None) or {}
    suggested = intensity_from_form(form) if form else "media"
    chosen = getattr(profile, "tracking_intensity", None)
    intensity = chosen if chosen in INTENSITIES else suggested
    source = "person" if chosen in INTENSITIES else ("enroll" if form else "default")
    context = GrowingContext.model_validate(getattr(profile, "growing_context", None) or {})
    return TrackingProfileRead(
        intensity=intensity, intensity_source=source, enroll_intensity=suggested,
        weekly_asks=WEEKLY_ASKS[intensity], growing_context=context, profile=getattr(profile, "profile", None),
    )


TOOL_LABELS = {
    "medidor_ph": "medidor de pH", "conductimetro": "conductímetro (CE)", "tensiometro": "tensiómetro",
    "sensor_humedad": "sensor de humedad de suelo", "termometro": "termómetro", "trampas_cromaticas":
    "trampas cromáticas", "malla_sombra": "malla de sombra", "cobertor": "cobertor / manta térmica",
    "riego_goteo": "riego por goteo", "temporizador_riego": "temporizador de riego", "lupa": "lupa",
    "balanza": "balanza",
}
BUDGET_LABELS = {"minimo": "casi nada", "bajo": "bajo", "medio": "medio", "alto": "alto"}


def growing_context_lines(read: TrackingProfileRead) -> list[str]:
    """The person's means, as plain lines for a prompt."""
    ctx = read.growing_context
    lines = [f"Intensidad de seguimiento elegida: {read.intensity} (hasta {read.weekly_asks} pedidos de datos por "
             "semana, sin contar riesgos urgentes)."]
    tools = [TOOL_LABELS.get(t, t) for t in ctx.tools] + ([ctx.other_tools] if ctx.other_tools else [])
    lines.append("Herramientas que tiene: " + (", ".join(tools) if tools else "no declaró ninguna (asumí solo manos, "
                                                "vista y un celular; no supongas instrumentos)") + ".")
    if ctx.weekly_hours is not None:
        lines.append(f"Tiempo que le dedica: unas {ctx.weekly_hours:g} horas por semana.")
    if ctx.budget:
        lines.append(f"Presupuesto para invertir: {BUDGET_LABELS[ctx.budget]}.")
    if ctx.notes:
        lines.append(f"Notas suyas: {ctx.notes}")
    return lines
