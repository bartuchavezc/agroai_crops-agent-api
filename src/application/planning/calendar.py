"""Planning calendar for a date range: reminders (recurring ones expanded into their occurrences), stage plans as
ranges and planned sowings, in one list the web app can draw as a week, a month or a year."""
from datetime import date, datetime, timedelta
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

MAX_OCCURRENCES = 400  # per reminder, whatever the range: a daily reminder over a year is 366

CalendarKind = Literal["reminder", "stage", "sowing"]


class CalendarItem(BaseModel):
    date: date
    kind: CalendarKind
    source: Optional[str] = None  # user | agent | plan
    ref_id: Optional[UUID] = None
    title: str
    stage: Optional[str] = None  # StageType, for kind=stage
    due_at: Optional[datetime] = None  # kind=reminder: the exact instant of this occurrence
    recurring: bool = False
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    status: Optional[str] = None


class CalendarRange(BaseModel):
    """A plan stage as a span (the year view draws these as bars)."""
    start: date
    end: date
    ref_id: UUID
    plan_id: UUID
    title: str
    stage: str
    field_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None


class CalendarResponse(BaseModel):
    since: date
    until: date
    items: list[CalendarItem]
    ranges: list[CalendarRange]


def step_days(recurrence: str, interval_days: Optional[int]) -> Optional[int]:
    return {"daily": 1, "weekly": 7}.get(recurrence) or (interval_days if recurrence == "every_n_days" else None)


def occurrences(
    due_at: datetime, recurrence: str, interval_days: Optional[int], series_until: Optional[date],
    window_start: datetime, window_end: datetime, tz: ZoneInfo,
) -> list[datetime]:
    """Instants of one reminder inside [window_start, window_end). Recurring ones repeat at the same wall-clock time
    of the user's zone (so a daylight-saving change doesn't move them). The current `due_at` is the earliest known
    occurrence: nothing is invented before it, since earlier ones were never recorded."""
    step = step_days(recurrence, interval_days)
    local = due_at.astimezone(tz)
    found: list[datetime] = []
    for n in range(MAX_OCCURRENCES):
        current = local if step is None else local + timedelta(days=step * n)
        if current >= window_end.astimezone(tz) or (series_until and current.date() > series_until):
            break
        if current >= window_start.astimezone(tz):
            found.append(current)
        if step is None:
            break
    return found
