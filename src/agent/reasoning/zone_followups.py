"""
Follow-ups in a zone analysis (see diagnosis_service._analyze_zone and src/application/followups/).

Before: the open follow-ups of the zone go to every pass as context, so a crop group can say "that is the aphid
we were already following" instead of reporting it as new. The follow-up pass — one call for every problem
photographed this time, never one per problem — gets each one's history, its last photo (ANTES, at a lower
resolution: it is only the reference) and the new one (AHORA).

After: what the analysis found becomes bitácora entries with their evidence — each evaluation, each new problem
(opened as a follow-up when its severity is medium or worse, proposed when low) — and a few suggested actions for
the person: close one that was not seen twice in a row, treat one that got worse. Closing is never automatic: a
badly framed photo must not close a pest that is still there.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.application.farm.schemas import FieldEventRead
from src.application.followups.schemas import FollowUpRead

from ..prompts.followups import FOLLOWUP_CLOSING, NO_BEFORE_PHOTO, NOW_LABEL, before_label, followup_header
from .periodic_report import FollowUpEvaluation, ZoneIssue, format_event_history
from .zone_photos import ZonePhoto

PREVIOUS_PHOTO_SIDE = 768  # the ANTES photo is a reference: a quarter of the pixels is plenty to compare against
HISTORY_ENTRIES = 8
CLOSE_CONFIDENCE = 0.7  # both of the two evaluations in a row that propose closing must be at least this sure
OPEN_SEVERITIES = ("medium", "high", "critical")  # a new problem this bad opens a follow-up on its own

EVOLUTION_LABEL = {"mejor": "mejor", "igual": "sin cambios", "peor": "peor", "no_visible": "no se ve"}


@dataclass
class FollowUpInput:
    """One follow-up photographed this time, with what the follow-up pass needs about it."""

    followup: FollowUpRead
    photos: list[ZonePhoto]
    history: list[FieldEventRead]  # its bitácora entries, newest first
    previous_photo: Optional[str] = None  # image identifier of its last photo before this report
    previous_at: Optional[datetime] = None
    previous_part: object = None  # the model-ready ANTES image, loaded by the caller
    previous_evaluations: list[tuple[str, float]] = field(default_factory=list)  # (evolution, confidence)


def open_followup_lines(followups: list[FollowUpRead]) -> list[str]:
    if not followups:
        return []
    lines = ["Seguimientos abiertos en esta zona (problemas ya detectados que se están siguiendo):"]
    for f in followups:
        since = f.created_at.date().isoformat()
        last = f" Última evaluación: {EVOLUTION_LABEL[f.last_evolution]}." if f.last_evolution else ""
        lines.append(f"- id={f.id}: {f.title} ({f.kind}, severidad {f.severity}), desde el {since}.{last}")
    return lines


def followup_input(
    followup: FollowUpRead, photos: list[ZonePhoto], history: list[FieldEventRead], current_images: set[str]
) -> FollowUpInput:
    """Picks the ANTES photo (the newest photo in its entries that isn't one of this report's) and its earlier
    evaluations out of its history."""
    previous = next(
        (
            (ev.identifier, e.occurred_at)
            for e in history for ev in e.evidence
            if ev.kind == "photo" and ev.identifier not in current_images
        ),
        (None, None),
    )
    evaluations = [
        (e.data["evolution"], float(e.data.get("confidence") or 0))
        for e in history if (e.data or {}).get("evolution")
    ]
    return FollowUpInput(followup, photos, history, previous[0], previous[1], None, evaluations)


def followup_pass_contents(inputs: list[FollowUpInput]) -> list:
    """Interleaved text and images: each follow-up's header and history, ANTES, AHORA."""
    contents: list = []
    for item in inputs:
        f = item.followup
        history = "; ".join(format_event_history(list(reversed(item.history[:HISTORY_ENTRIES]))))
        contents.append(followup_header(f.id, f.title, f.kind, f.created_at.date(), f.photo_hint, history))
        if item.previous_part is not None:
            contents += [before_label(item.previous_at.date()), item.previous_part]
        else:
            contents.append(NO_BEFORE_PHOTO)
        contents.append(NOW_LABEL)
        contents += [p.part for p in item.photos]
    contents.append(FOLLOWUP_CLOSING)
    return contents


def proposes_close(current: FollowUpEvaluation, previous: list[tuple[str, float]]) -> bool:
    """Not seen now and not seen the time before, both with enough confidence."""
    return (
        current.evolution == "no_visible" and current.confidence >= CLOSE_CONFIDENCE
        and bool(previous) and previous[0][0] == "no_visible" and previous[0][1] >= CLOSE_CONFIDENCE
    )


def evaluation_notes(followup: FollowUpRead, evaluation: FollowUpEvaluation) -> str:
    return f"Seguimiento de {followup.title}: {EVOLUTION_LABEL[evaluation.evolution]}. {evaluation.evidence}".strip()


def new_issues(issues: list[ZoneIssue], followed_ids: set[str], zone_lot_ids: set[str]) -> list[ZoneIssue]:
    """The problems that aren't one already being followed, once each (two crop groups may both mention a
    zone-wide one), keeping only the lots that are really in the zone."""
    seen: set[str] = set()
    out = []
    for issue in issues:
        key = issue.title.strip().lower()
        if (issue.followup_id and issue.followup_id in followed_ids) or not key or key in seen:
            continue
        seen.add(key)
        out.append(issue.model_copy(update={"lot_ids": [i for i in issue.lot_ids if i in zone_lot_ids]}))
    return out


def issue_photo(issue: ZoneIssue, image_ids: list[str]) -> Optional[str]:
    if issue.photo_number and 1 <= issue.photo_number <= len(image_ids):
        return image_ids[issue.photo_number - 1]
    return image_ids[0] if image_ids else None
