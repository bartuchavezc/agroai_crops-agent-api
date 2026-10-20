"""A field's current state in one read, for the agent (get_farm_snapshot) and the home screen's "Estado actual":
zones with their active lots and last bitácora entry, lots by status, what was logged lately, the next tasks,
today's reminders, pH and the last analysis."""
from collections import Counter
from datetime import date, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.application.planning.schemas import ReminderRead
from src.application.tasks.schemas import TaskRead
from src.shared.domain.actor import Actor
from src.shared.domain.locale import today_in

from .log import LogItem
from .schemas import ActiveLotSummary
from .summary import end_of_local_day

RECENT_LOG = 6
NEXT_TASKS = 5


class SnapshotZone(BaseModel):
    id: UUID
    label: str
    area_m2: Optional[float] = None
    ph: Optional[float] = None  # the zone's own soil, else the field's
    lots: list[ActiveLotSummary] = Field(default_factory=list)
    last_entry: Optional[LogItem] = None


class SnapshotAnalysis(BaseModel):
    report_id: UUID
    at: datetime
    report_type: str
    zone_id: Optional[UUID] = None
    summary: Optional[str] = None


class FieldSnapshot(BaseModel):
    field_id: UUID
    field_name: str
    season: Optional[str] = None  # the filter applied to the lots, if any
    ph: Optional[float] = None  # the field's topsoil pH (INTA / SoilGrids)
    lots_by_status: dict[str, int] = Field(default_factory=dict, description="Every lot of the field, by status")
    zones: list[SnapshotZone]
    unzoned_lots: list[ActiveLotSummary] = Field(default_factory=list)
    recent_log: list[LogItem] = Field(default_factory=list, description="Newest first")
    next_tasks: list[TaskRead] = Field(default_factory=list, description="Open, by due date")
    open_tasks: int = 0
    reminders_today: list[ReminderRead] = Field(default_factory=list)
    last_analysis: Optional[SnapshotAnalysis] = None


def _field_ph(field) -> Optional[float]:
    soil = field.soil_context
    if soil is None:
        return None
    if soil.ph_estimate is not None:
        return soil.ph_estimate
    layers = soil.soilgrids.depths.values() if soil.soilgrids else []
    return next((layer.ph for layer in layers if layer.ph is not None), None)


class FieldSnapshotService:
    def __init__(self, farm_service, reports_service, planning_service, task_service, log_service):
        self.farm = farm_service
        self.reports = reports_service
        self.planning = planning_service
        self.tasks = task_service
        self.log = log_service

    async def snapshot(self, actor: Actor, field_id: UUID, season: Optional[str] = None) -> FieldSnapshot:
        field = await self.farm.get_field(actor, field_id)
        overview = next((o for o in await self.farm.overview(actor) if o.field.id == field_id), None)
        zones = overview.zones if overview else await self.farm.list_zones(actor, field_id)
        active = [lot for lot in (overview.active_lots if overview else []) if not season or lot.season == season]
        every_lot = [lot for lot in await self.farm.list_lots(actor, field_id=field_id)
                     if not season or lot.season == season]

        # the newest entries of the whole field; the first one of each zone is that zone's last entry
        page = await self.log.log(actor, field_id=field_id, limit=50)
        items = [item for day in page.days for item in day.items]
        last_by_zone: dict[UUID, LogItem] = {}
        for item in items:
            if item.zone_id and item.zone_id not in last_by_zone:
                last_by_zone[item.zone_id] = item

        field_ph = _field_ph(field)
        zone_ids = {z.id for z in zones}
        snapshot_zones = [
            SnapshotZone(
                id=z.id, label=z.label, area_m2=z.area_m2, ph=z.soil.ph if z.soil.ph is not None else field_ph,
                lots=[lot for lot in active if z.id in (lot.zone_ids or [lot.zone_id])],
                last_entry=last_by_zone.get(z.id),
            )
            for z in zones
        ]

        open_tasks = await self.tasks.list_tasks(actor, field_id=field_id, open_only=True)
        open_tasks.sort(key=lambda t: (t.due_date is None, t.due_date or date.max, t.created_at))

        tz = ZoneInfo(actor.timezone) if actor.timezone else ZoneInfo("UTC")
        reminders = await self.planning.list_reminders(
            actor, status="activo", until=end_of_local_day(today_in(actor.timezone), tz), field_id=field_id, limit=20,
        )

        reports = await self.reports.list_reports(actor, field_id=field_id, status="ANALYSIS_COMPLETED", limit=1)
        last = reports[0] if reports else None

        return FieldSnapshot(
            field_id=field.id, field_name=field.name, season=season, ph=field_ph,
            lots_by_status=dict(Counter(lot.status for lot in every_lot)),
            zones=snapshot_zones,
            unzoned_lots=[lot for lot in active if not zone_ids.intersection(lot.zone_ids or [lot.zone_id])],
            recent_log=items[:RECENT_LOG],
            next_tasks=open_tasks[:NEXT_TASKS], open_tasks=len(open_tasks),
            reminders_today=reminders,
            last_analysis=SnapshotAnalysis(
                report_id=last.id, at=last.created_at, report_type=last.report_type, zone_id=last.zone_id,
                summary=last.summary,
            ) if last else None,
        )
