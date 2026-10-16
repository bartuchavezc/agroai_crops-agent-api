"""How far along a crop cycle is against what is expected of it, and whether it is behind or affected.

`expected_pct` and the stage come from dates and the stage plan (the plan saved for the cycle, else the crop's
template); `status` comes from the latest completed analysis that covered the cycle (a single-crop periodic report
or a zone tracking report), because the dates alone cannot tell if a crop is doing badly."""
from datetime import date, timedelta
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from src.shared.domain.actor import Actor
from src.shared.domain.locale import today_in

ProgressStatus = Literal["ok", "late", "affected", "unknown"]
_BAD_HEALTH = {"poor", "critical"}


class CycleProgress(BaseModel):
    crop_cycle_id: UUID
    expected_pct: Optional[float] = None  # 0-100; null when the sowing date is unknown
    current_stage: Optional[str] = None  # StageType id (vegetativo, floracion, cosecha...)
    current_stage_name: Optional[str] = None
    next_stage_at: Optional[date] = None
    status: ProgressStatus = "unknown"  # unknown = no completed analysis and not past the expected harvest
    reason: Optional[str] = None
    evidence_report_id: Optional[UUID] = None
    evidence_date: Optional[date] = None


def expected_pct(planting: Optional[date], harvest: Optional[date], today: date) -> Optional[float]:
    """Share of the planting -> expected harvest span already elapsed, clamped to 0-100."""
    if planting is None or harvest is None or harvest <= planting:
        return None
    return round(min(max((today - planting).days / (harvest - planting).days, 0.0), 1.0) * 100, 1)


def current_and_next(
    stages: list[tuple[str, str, date]], today: date
) -> tuple[Optional[tuple[str, str]], Optional[date]]:
    """((stage id, name) of the stage in progress, start of the next one) for stages given as (id, name, start)."""
    ordered = sorted(stages, key=lambda s: s[2])
    current = None
    for stage_id, name, start in ordered:
        if start <= today:
            current = (stage_id, name)
    upcoming = next((start for _, _, start in ordered if start > today), None)
    return current, upcoming


def assess(entry: Optional[dict], harvest: Optional[date], today: date) -> tuple[ProgressStatus, Optional[str]]:
    """Status from one analysis entry of the cycle (periodic result or zone-crop assessment)."""
    entry = entry or {}
    stress = entry.get("stress_signals") or []
    if stress or entry.get("health_status") in _BAD_HEALTH:
        return "affected", ", ".join(stress[:3]) if stress else f"salud {entry.get('health_status')}"
    if entry.get("growth_on_track") is False:
        return "late", "el último análisis ve el crecimiento por detrás de lo esperado"
    if harvest is not None and today > harvest:
        return "late", "pasó la fecha esperada de cosecha"
    if entry.get("growth_on_track") is True or entry.get("health_status"):
        return "ok", None
    return "unknown", None


class CycleProgressService:
    def __init__(self, farm_service, planning_service, reports_service):
        self.farm = farm_service
        self.planning = planning_service
        self.reports = reports_service

    async def _stages(self, actor: Actor, cycle) -> list[tuple[str, str, date]]:
        plans = await self.planning.repo.list_plans(actor.account_id, crop_cycle_id=cycle.id)
        if plans:
            stages, _, _ = await self.planning.repo.plan_children(plans[0].id)
            if stages:
                return [(s.stage, s.name, s.start_date) for s in stages]
        if cycle.planting_date is None:
            return []
        proposal = await self.planning.propose_cycle_plan(actor, cycle.id)
        return [(s.stage, s.name, s.start_date) for s in proposal.stages]

    async def _latest_entry(self, actor: Actor, cycle) -> tuple[Optional[dict], Optional[object]]:
        reports = await self.reports.list_reports(
            actor, crop_cycle_id=cycle.id, report_type="periodic", status="ANALYSIS_COMPLETED", limit=1
        )
        if not reports:
            return None, None
        report = reports[0]
        data = report.raw_analysis_data or {}
        entry = data.get("llm_structured_periodic")
        if not entry:
            crops = (data.get("llm_structured_zone") or {}).get("crops") or []
            entry = next((c for c in crops if c.get("crop_cycle_id") == str(cycle.id)), None)
        return entry, report

    async def progress(self, actor: Actor, cycle_id: UUID) -> CycleProgress:
        cycle = await self.farm.get_crop_cycle(actor, cycle_id)
        crop = await self.farm.get_crop_master(actor, cycle.crop_master_id)
        today = today_in(actor.timezone)
        harvest = cycle.expected_harvest_date
        if harvest is None and cycle.planting_date and crop.growth_period_days:
            harvest = cycle.planting_date + timedelta(days=crop.growth_period_days)

        stages = await self._stages(actor, cycle)
        current, upcoming = current_and_next(stages, today)
        entry, report = await self._latest_entry(actor, cycle)
        status, reason = assess(entry, harvest, today)
        return CycleProgress(
            crop_cycle_id=cycle.id,
            expected_pct=expected_pct(cycle.planting_date, harvest, today),
            current_stage=current[0] if current else None,
            current_stage_name=current[1] if current else None,
            next_stage_at=upcoming,
            status=status,
            reason=reason,
            evidence_report_id=report.id if report is not None and entry else None,
            evidence_date=report.created_at.date() if report is not None and entry else None,
        )
