from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.application.planning.calendar import occurrences

TZ = ZoneInfo("America/Bogota")


def at(day, hour=9):
    return datetime(2026, 10, day, hour, tzinfo=TZ)


def test_one_shot_reminders_appear_only_inside_the_window():
    assert occurrences(at(10), "none", None, None, at(1), at(31), TZ) == [at(10)]
    assert occurrences(at(10), "none", None, None, at(11), at(31), TZ) == []
    assert occurrences(at(10), "none", None, None, at(1), at(10), TZ) == []  # the end is exclusive


def test_recurring_reminders_expand_from_the_current_occurrence_and_stop_at_until():
    week = occurrences(at(1), "daily", None, None, at(3), at(8), TZ)
    assert [d.day for d in week] == [3, 4, 5, 6, 7]
    assert [d.day for d in occurrences(at(2), "weekly", None, None, at(1), at(31), TZ)] == [2, 9, 16, 23, 30]
    assert [d.day for d in occurrences(at(1), "every_n_days", 10, None, at(1), at(31, 10), TZ)] == [1, 11, 21, 31]
    assert [d.day for d in occurrences(at(1), "daily", None, date(2026, 10, 4), at(1), at(31), TZ)] == [1, 2, 3, 4]
    assert occurrences(at(20), "daily", None, None, at(1), at(10), TZ) == []  # nothing before the first known one


def test_a_daily_reminder_over_a_long_range_is_capped():
    year = occurrences(at(1), "daily", None, None, at(1), at(1) + timedelta(days=2000), TZ)
    assert len(year) == 400


def test_recurring_reminders_keep_their_wall_clock_across_a_clock_change():
    ny = ZoneInfo("America/New_York")
    start = datetime(2026, 10, 31, 9, tzinfo=ny)  # DST ends on 1 Nov 2026
    days = occurrences(start, "daily", None, None, start, start + timedelta(days=4), ny)
    assert {d.hour for d in days} == {9} and len(days) == 4
