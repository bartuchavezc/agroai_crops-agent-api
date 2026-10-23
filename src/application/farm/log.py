"""The bitácora: everything logged on a field, a zone or one lot, grouped by day.

A lot's bitácora holds every event that reached it (logged on the lot, on its zone or on the whole field —
event_lots keeps that) and the completed analyses that covered it; a zone's, the events logged there and its
analyses; a field's, all of it. Done tasks join in once they exist (see the tasks module)."""
from datetime import date, datetime
from typing import Any, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError

LogKind = Literal["event", "analysis", "task"]
MAX_LIMIT = 200


class LogItem(BaseModel):
    kind: LogKind
    at: datetime
    title: str
    detail: Optional[str] = None
    ref_id: Optional[UUID] = None  # the event / report / task it came from
    type: Optional[str] = None  # event type, report type
    quantity: Optional[float] = None
    unit: Optional[str] = None
    zone_id: Optional[UUID] = None
    lot_ids: list[UUID] = Field(default_factory=list)
    source: Optional[str] = None  # user | agent | system
    outcome: Optional[str] = None  # done | skipped (events)
    reason: Optional[str] = None  # why it was skipped / what caused a loss
    image_identifier: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


class LogDay(BaseModel):
    date: date
    items: list[LogItem]


class LogPage(BaseModel):
    days: list[LogDay]
    next_before: Optional[datetime] = Field(None, description="Pass as `before` for older entries; null at the end")


class LogService:
    def __init__(self, farm_service, reports_service, task_service=None):
        self.farm = farm_service
        self.reports = reports_service
        self.tasks = task_service

    async def log(
        self,
        actor: Actor,
        field_id: Optional[UUID] = None,
        zone_id: Optional[UUID] = None,
        lot_id: Optional[UUID] = None,
        before: Optional[datetime] = None,
        since: Optional[datetime] = None,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> LogPage:
        """Newest first, `limit` entries, grouped by the user's local day. Exactly one of field/zone/lot."""
        if sum(x is not None for x in (field_id, zone_id, lot_id)) != 1:
            raise InvalidInputError("Give exactly one of field_id, zone_id or lot_id.")
        if lot_id:
            await self.farm.get_lot(actor, lot_id)  # 404 for another account's
        elif zone_id:
            await self.farm.get_zone(actor, zone_id)
        else:
            await self.farm.get_field(actor, field_id)
        limit = min(max(limit, 1), MAX_LIMIT)
        # Each source gives its newest `limit`; the newest `limit` of the union are all among those.
        events = await self.farm.list_events(
            actor, field_id=field_id, zone_id=zone_id, lot_id=lot_id, before=before, since=since, limit=limit,
            event_type=event_type,
        )
        items = [
            LogItem(
                kind="event", at=e.occurred_at, title=e.type, detail=e.notes, ref_id=e.id, type=e.type,
                quantity=e.quantity, unit=e.unit, zone_id=e.zone_id, lot_ids=e.lot_ids, source=e.source,
                image_identifier=e.image_identifier, data=e.data, outcome=e.outcome, reason=e.reason,
            )
            for e in events
        ]
        if event_type is None:
            reports = await self.reports.list_reports(
                actor, field_id=field_id, zone_id=zone_id, lot_id=lot_id, status="ANALYSIS_COMPLETED",
                until=before, since=since, limit=limit,
            )
            items += [
                LogItem(
                    kind="analysis", at=r.created_at, title=r.title or "Seguimiento", detail=r.summary, ref_id=r.id,
                    type=r.report_type, zone_id=r.zone_id, lot_ids=r.lot_ids or ([r.lot_id] if r.lot_id else []),
                    image_identifier=r.image_identifier, data={"reason": r.reason} if r.reason else {},
                )
                for r in reports if before is None or r.created_at < before
            ]
            if self.tasks is not None:
                items += await self.tasks.log_items(
                    actor, field_id=field_id, zone_id=zone_id, lot_id=lot_id, before=before, since=since, limit=limit
                )
        items.sort(key=lambda i: i.at, reverse=True)
        items = items[:limit]
        tz = ZoneInfo(actor.timezone) if actor.timezone else None
        days: list[LogDay] = []
        for item in items:
            day = item.at.astimezone(tz).date() if tz else item.at.date()
            if not days or days[-1].date != day:
                days.append(LogDay(date=day, items=[]))
            days[-1].items.append(item)
        return LogPage(days=days, next_before=items[-1].at if len(items) == limit else None)
