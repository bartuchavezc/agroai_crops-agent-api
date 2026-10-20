"""
How a zone's active lots are grouped for the fanned-out analysis, and how the N group results (plus
the overview and synthesis passes) become the one ZonePeriodicReportResult the report persists. Pure: no I/O,
no Gemini — see zone_task_loop.py for the task scheduler that calls these, and diagnosis_service.py for the
Gemini calls themselves.
"""
import logging
from dataclasses import dataclass

from .analysis_context import crop_slug
from .periodic_report import (
    ZoneCropAssessment,
    ZoneGroupAssessment,
    ZoneOverviewResult,
    ZonePeriodicReportResult,
    ZoneSynthesisResult,
)

logger = logging.getLogger(__name__)

# Bounds the per-call CYCLE context (progress + events) of a group, not its reference cost: crops sharing a
# ficha slug cost the same whether a group holds one of them or four.
MAX_CYCLES_PER_GROUP = 4

HEALTH_SEVERITY = ("excellent", "good", "fair", "poor", "critical")
RISK_SEVERITY = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class CropGroup:
    """Crops that share a ficha técnica slug (so loading it once covers all of them), or share having none
    (so there is nothing to load either way). `id` is unique across a zone's groups."""

    id: str
    cycle_ids: tuple[str, ...]
    crop_names: tuple[str, ...]


def group_cycles(cycles: list[tuple[str, str]]) -> list[CropGroup]:
    """`cycles`: [(cycle_id, crop_name), ...] in the order the zone report lists them. "Similar" means same
    ficha slug (what actually drives the reference cost of a call) — not botanical family, which is
    nullable free text and commonly missing on account-created crops."""
    order: list[str] = []
    by_slug: dict[str, list[tuple[str, str]]] = {}
    for cycle_id, crop_name in cycles:
        slug = crop_slug(crop_name) or "_sin_ficha"
        by_slug.setdefault(slug, [])
        if slug not in order:
            order.append(slug)
        by_slug[slug].append((cycle_id, crop_name))

    groups: list[CropGroup] = []
    for slug in order:
        entries = by_slug[slug]
        chunks = [entries[i : i + MAX_CYCLES_PER_GROUP] for i in range(0, len(entries), MAX_CYCLES_PER_GROUP)]
        for i, chunk in enumerate(chunks):
            group_id = slug if len(chunks) == 1 else f"{slug}-{i + 1}"
            groups.append(
                CropGroup(
                    id=group_id, cycle_ids=tuple(c for c, _ in chunk), crop_names=tuple(n for _, n in chunk)
                )
            )
    return groups


def _worst(values: list[str], order: tuple[str, ...], default: str) -> str:
    """The most severe value in `order`'s ranking; values outside `order` (e.g. "unknown") are ignored."""
    ranked = [v for v in values if v in order]
    return max(ranked, key=order.index) if ranked else default


def _missing_crop_entry(cycle_id: str) -> ZoneCropAssessment:
    """A conservative stand-in for a cycle that no group's result echoed back (its group's task failed, or
    the model dropped/garbled the id) — `crop_entry()` and the frontend must never lose a row outright."""
    return ZoneCropAssessment(
        lot_id=cycle_id,
        crop_name="(no evaluado)",
        visible_in_photos=False,
        growth_stage="no evaluado",
        health_status="unknown",
        health_summary="No se pudo evaluar este cultivo en este seguimiento.",
        expected_vs_actual="No se pudo evaluar.",
        harvest_ready=False,
        harvest_verdict="No se pudo evaluar.",
    )


def merge_zone_result(
    cycle_ids: list[str],
    resolved_groups: list[ZoneGroupAssessment],
    overview: ZoneOverviewResult,
    synthesis: ZoneSynthesisResult,
) -> ZonePeriodicReportResult:
    """Combine the fanned-out results into the one shape the report persists and the frontend reads. Code
    merge for the "worst of" / boolean fields (unambiguous, deterministic); the synthesis pass already did
    the genuinely cross-cutting judgment calls (zone_summary, interactions, shared_risks, ...) — this does
    not re-derive them.

    `resolved_groups` is one ZoneGroupAssessment per group, already the recheck's result where a recheck ran
    (see zone_task_loop.py) — a failed group simply isn't in this list.
    """
    crops: list[ZoneCropAssessment] = []
    seen_ids: set[str] = set()
    for group in resolved_groups:
        for crop in group.crops:
            crops.append(crop)
            seen_ids.add(crop.lot_id)
    for cycle_id in cycle_ids:
        if cycle_id not in seen_ids:
            logger.warning(
                f"Zone analysis: lot_id={cycle_id} missing from every group/recheck result "
                "(its group failed, or the model dropped/garbled the id) — filled in defensively"
            )
            crops.append(_missing_crop_entry(cycle_id))

    return ZonePeriodicReportResult(
        zone_summary=synthesis.zone_summary,
        overall_health=_worst([c.health_status for c in crops], HEALTH_SEVERITY, "good"),
        crops=crops,
        unlisted_plants=overview.unlisted_plants,
        interactions=synthesis.interactions,
        past_actions_assessment=synthesis.past_actions_assessment,
        objectives_assessment=synthesis.objectives_assessment,
        shared_risks=synthesis.shared_risks,
        risk_severity=_worst([g.group_risk_severity for g in resolved_groups], RISK_SEVERITY, "low"),
        recommendations=synthesis.recommendations,
        confidence=min((g.confidence for g in resolved_groups), default=0.5),
        needs_human_expert=any(g.needs_human_expert for g in resolved_groups),
    )
