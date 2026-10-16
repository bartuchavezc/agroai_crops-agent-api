"""One zone's history in a single list: field events, completed analyses and reminders that were done."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from src.shared.domain.actor import Actor

TimelineKind = Literal["event", "analysis", "reminder"]
MAX_LIMIT = 200


class TimelineItem(BaseModel):
    kind: TimelineKind
    at: datetime
    title: str
    detail: Optional[str] = None
    ref_id: Optional[UUID] = None  # the event / report / reminder it came from
    type: Optional[str] = None  # event type, report type, or the reminder's source


class ZoneTimelineService:
    def __init__(self, farm_service, reports_service, planning_repository):
        self.farm = farm_service
        self.reports = reports_service
        self.planning = planning_repository

    async def timeline(
        self, actor: Actor, zone_id: UUID, before: Optional[datetime] = None, limit: int = 50
    ) -> list[TimelineItem]:
        """Newest first. `before` pages back in time: pass the `at` of the last item received."""
        await self.farm.get_zone(actor, zone_id)  # 404 for a zone of another account
        limit = min(max(limit, 1), MAX_LIMIT)
        # Each source gives its newest `limit`; the newest `limit` of the union are all among those.
        events = await self.farm.list_events(actor, zone_id=zone_id, before=before, limit=limit)
        reports = await self.reports.list_reports(
            actor, zone_id=zone_id, status="ANALYSIS_COMPLETED", until=before, limit=limit
        )
        done = await self.planning.completions(actor.account_id, zone_id=zone_id, before=before, limit=limit)
        items = [
            TimelineItem(kind="event", at=e.occurred_at, title=e.type, detail=e.notes, ref_id=e.id, type=e.type)
            for e in events
        ] + [
            TimelineItem(
                kind="analysis", at=r.created_at, title=r.title or "Seguimiento", detail=r.summary, ref_id=r.id,
                type=r.report_type,
            )
            for r in reports if before is None or r.created_at < before
        ] + [
            TimelineItem(kind="reminder", at=c.completed_at, title=c.title, detail=c.description, ref_id=c.reminder_id)
            for c in done
        ]
        items.sort(key=lambda i: i.at, reverse=True)
        return items[:limit]
