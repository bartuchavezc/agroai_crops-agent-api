"""A field's home screen in one call: general state, zones with their last analysis, active alerts, today's
reminders and the irrigation outlook. The web app used to compose this from about eight requests."""
import logging
from datetime import date, datetime, time, timedelta
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from src.application.alerts.schemas import Alert
from src.application.irrigation.schemas import FieldIrrigationResult
from src.application.planning.schemas import ReminderRead
from src.shared.domain.actor import Actor
from src.shared.domain.locale import today_in

from .schemas import ActiveCycleSummary, FieldRead, FieldZoneRead

logger = logging.getLogger(__name__)

FieldState = Literal["ok", "attention", "alert", "unknown"]
_RISKY_HEALTH = {"poor", "critical"}
_RISKY_SEVERITY = {"high", "critical"}


class ZoneAnalysis(BaseModel):
    report_id: UUID
    at: datetime
    summary: Optional[str] = None
    overall_health: Optional[str] = None  # excellent | good | fair | poor | critical
    risk_severity: Optional[str] = None  # low | medium | high | critical
    image_identifier: Optional[str] = None  # first photo of the report


class ZoneSummary(BaseModel):
    zone: FieldZoneRead
    active_cycles: list[ActiveCycleSummary] = []
    last_analysis: Optional[ZoneAnalysis] = None


class FieldSummary(BaseModel):
    field: FieldRead
    status: FieldState
    status_reasons: list[str] = []
    zones: list[ZoneSummary]
    unzoned_cycles: list[ActiveCycleSummary] = []  # active crops of the field that belong to no zone
    alerts: list[Alert]
    reminders_today: list[ReminderRead]  # pending, due by the end of the user's day (overdue ones included)
    irrigation: Optional[FieldIrrigationResult] = None  # null if the field has no coordinates or the data is down


def field_state(alerts: list, zones: list[ZoneSummary], irrigation: Optional[FieldIrrigationResult]) -> tuple[
    FieldState, list[str]
]:
    """The general state and why: an alert of high severity, or else any sign that needs a look."""
    if any(a.severity in _RISKY_SEVERITY for a in alerts):
        return "alert", [a.title for a in alerts if a.severity in _RISKY_SEVERITY][:3]
    reasons = [a.title for a in alerts]
    for zone in zones:
        last = zone.last_analysis
        if last and (last.overall_health in _RISKY_HEALTH or last.risk_severity in _RISKY_SEVERITY):
            reasons.append(f"{zone.zone.label}: el último seguimiento marca riesgo")
    if irrigation is not None and irrigation.field_status == "regar":
        reasons.append("Hay que regar")
    if reasons:
        return "attention", reasons
    has_data = irrigation is not None or any(z.last_analysis for z in zones)
    return ("ok" if has_data else "unknown"), []


def end_of_local_day(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)


class FieldSummaryService:
    def __init__(self, farm_service, reports_service, planning_service, alert_service, irrigation_service):
        self.farm = farm_service
        self.reports = reports_service
        self.planning = planning_service
        self.alerts = alert_service
        self.irrigation = irrigation_service

    async def summary(self, actor: Actor, field_id: UUID) -> FieldSummary:
        field = await self.farm.get_field(actor, field_id)
        overview = next((o for o in await self.farm.overview(actor) if o.field.id == field_id), None)
        zones = overview.zones if overview else await self.farm.list_zones(actor, field_id)
        cycles = overview.active_cycles if overview else []

        # One query for the latest analyses of the whole field (newest first), then the first per zone.
        reports = await self.reports.list_reports(
            actor, field_id=field_id, report_type="periodic", status="ANALYSIS_COMPLETED", limit=100
        )
        last_by_zone: dict[UUID, ZoneAnalysis] = {}
        for report in reports:
            if report.zone_id and report.zone_id not in last_by_zone:
                data = (report.raw_analysis_data or {}).get("llm_structured_zone") or {}
                photos = report.image_identifiers or ([report.image_identifier] if report.image_identifier else [])
                last_by_zone[report.zone_id] = ZoneAnalysis(
                    report_id=report.id, at=report.created_at, summary=report.summary,
                    overall_health=data.get("overall_health"), risk_severity=data.get("risk_severity"),
                    image_identifier=photos[0] if photos else None,
                )
        zone_summaries = [
            ZoneSummary(
                zone=z, active_cycles=[c for c in cycles if c.zone_id == z.id], last_analysis=last_by_zone.get(z.id)
            )
            for z in zones
        ]
        zone_ids = {z.id for z in zones}

        tz = ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("UTC")
        alerts = await self.alerts.get_active_alerts(actor, field_id=field_id)
        reminders = await self.planning.list_reminders(
            actor, status="pendiente", until=end_of_local_day(today_in(actor.timezone), tz), field_id=field_id,
            limit=100,
        )
        irrigation = None
        if field.latitude is not None and field.longitude is not None:
            try:
                irrigation = await self.irrigation.compute(actor, field_id)
            except Exception:  # noqa: BLE001 - the home screen is worth showing without it
                logger.exception("Irrigation outlook unavailable for the field summary")
        state, reasons = field_state(alerts, zone_summaries, irrigation)
        return FieldSummary(
            field=field, status=state, status_reasons=reasons, zones=zone_summaries,
            unzoned_cycles=[c for c in cycles if c.zone_id not in zone_ids], alerts=alerts,
            reminders_today=reminders, irrigation=irrigation,
        )
