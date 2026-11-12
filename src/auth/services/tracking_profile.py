"""How closely the agent follows a person's crops, and what the person has to work with.

Prediction always runs (the agent keeps a tracking plan per lot and simulates what it can't see); the intensity only
sets how often it asks the person for a check — a photo, a description, a measurement. It starts from the enrollment
answers and the person can change it from their profile at any time. `growing_context` is what the person has and how
they work, in their own words — never a fixed list: they write it in their profile and the agent adds what they mention
in the chat. The planner only proposes what fits it, and asks when it doesn't know."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

TrackingIntensity = Literal["baja", "media", "alta"]
INTENSITIES: tuple[str, ...] = ("baja", "media", "alta")

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


class Resource(BaseModel):
    """Something the person has to work with, in their own words: «tester de pH barato», «botellas como goteo»,
    «una tarde por semana». Never a catalog: what they say is what it is."""
    name: str = Field(min_length=1, max_length=120)
    note: Optional[str] = Field(default=None, max_length=300)
    source: Literal["person", "agent"] = "person"  # typed in the profile, or noted by the agent from the chat
    added_at: Optional[datetime] = None


_LEGACY_TOOLS = {  # the first version stored keys of a fixed list: kept as the words they stood for
    "medidor_ph": "medidor de pH", "conductimetro": "conductímetro (CE)", "tensiometro": "tensiómetro",
    "sensor_humedad": "sensor de humedad de suelo", "termometro": "termómetro", "trampas_cromaticas":
    "trampas cromáticas", "malla_sombra": "malla de sombra", "cobertor": "cobertor / manta térmica",
    "riego_goteo": "riego por goteo", "temporizador_riego": "temporizador de riego", "lupa": "lupa",
    "balanza": "balanza",
}
_LEGACY_BUDGET = {"minimo": "casi nada", "bajo": "bajo", "medio": "medio", "alto": "alto"}


class GrowingContext(BaseModel):
    """What the person has and how they work, as they tell it. The agent reads it, adds to it from the conversation
    (update_growing_means) and asks when a check depends on something it doesn't know they have."""
    resources: list[Resource] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, max_length=2000, description="Time, budget, how they work: free text")

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        """Contexts saved with the old fixed fields become resources and notes, in words: nothing is lost."""
        if not isinstance(data, dict) or not any(k in data for k in ("tools", "other_tools", "weekly_hours", "budget")):
            return data
        data = dict(data)
        resources = list(data.get("resources") or [])
        names = {(r.get("name") if isinstance(r, dict) else r.name).lower() for r in resources}
        for key in data.pop("tools", None) or []:
            name = _LEGACY_TOOLS.get(key, key)
            if name.lower() not in names:
                resources.append({"name": name, "source": "person"})
        if other := data.pop("other_tools", None):
            resources.append({"name": other[:120], "source": "person"})
        extra = []
        if (hours := data.pop("weekly_hours", None)) is not None:
            extra.append(f"Le dedica unas {hours:g} horas por semana.")
        if budget := data.pop("budget", None):
            extra.append(f"Presupuesto para invertir: {_LEGACY_BUDGET.get(budget, budget)}.")
        data["resources"] = resources
        data["notes"] = " ".join([*([data["notes"]] if data.get("notes") else []), *extra]) or None
        return data


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


def growing_context_lines(read: TrackingProfileRead) -> list[str]:
    """The person's means, in their own words, as plain lines for a prompt."""
    ctx = read.growing_context
    lines = [f"Intensidad de seguimiento elegida: {read.intensity} (hasta {read.weekly_asks} pedidos de datos por "
             "semana, sin contar riesgos urgentes)."]
    if ctx.resources:
        lines.append("Con qué cuenta (en sus palabras): " + "; ".join(
            r.name + (f" ({r.note})" if r.note else "") for r in ctx.resources) + ".")
    else:
        lines.append("Todavía no sabés con qué cuenta: no supongas instrumentos; si un chequeo depende de uno, "
                     "preguntá de forma natural si lo tiene.")
    if ctx.notes:
        lines.append(f"Cómo trabaja, en sus palabras: {ctx.notes}")
    return lines


def merge_resources(ctx: GrowingContext, add: list[dict], remove: list[str], source: str,
                    notes: Optional[str] = None) -> GrowingContext:
    """Add (or update the note of) resources and drop others, matching names without case."""
    from src.shared.domain.base import utcnow

    gone = {r.strip().lower() for r in remove if r.strip()}
    kept = [r for r in ctx.resources if r.name.lower() not in gone]
    by_name = {r.name.lower(): r for r in kept}
    for item in add:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        note = (str(item["note"]).strip() or None) if item.get("note") else None
        if name.lower() in by_name:
            if note:
                by_name[name.lower()].note = note
            continue
        resource = Resource(name=name, note=note, source=source, added_at=utcnow())
        kept.append(resource)
        by_name[name.lower()] = resource
    return GrowingContext(resources=kept, notes=ctx.notes if notes is None else (notes.strip() or None))
