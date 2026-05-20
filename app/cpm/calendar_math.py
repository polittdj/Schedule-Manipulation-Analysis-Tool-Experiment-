"""Working-time arithmetic over a Calendar.

The CPM engine works in integer working-minute offsets and never touches wall-clock time.
These helpers exist to (a) convert working minutes to working days for presentation and
(b) map working time onto real dates — used by the boundary-equivalence tests and any future
presentation layer. The working window each day is ``[day_start_minute, day_start_minute +
hours_per_day*60)``; intraday breaks (lunch) are not modelled.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.models import Calendar


def is_working_day(calendar: Calendar, day: date) -> bool:
    return day.isoweekday() in calendar.working_weekdays and day not in calendar.holidays


def minutes_to_working_days(minutes: int, calendar: Calendar) -> float:
    """Convert working minutes to working days (the forensic presentation unit)."""
    return minutes / (calendar.hours_per_day * 60)


def _minute_of_day(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def _at(day: date, minute_of_day: int) -> datetime:
    return datetime(day.year, day.month, day.day) + timedelta(minutes=minute_of_day)


def _next_working_day(calendar: Calendar, day: date) -> date:
    nxt = day + timedelta(days=1)
    while not is_working_day(calendar, nxt):
        nxt += timedelta(days=1)
    return nxt


def _canonical(
    calendar: Calendar, day: date, minute: int, day_open: int, day_close: int
) -> tuple[date, int]:
    """Snap (day, minute) forward to the first valid working instant at or after it."""
    while True:
        if not is_working_day(calendar, day):
            day = _next_working_day(calendar, day)
            minute = day_open
            continue
        if minute < day_open:
            minute = day_open
        if minute >= day_close:
            day = _next_working_day(calendar, day)
            minute = day_open
            continue
        return day, minute


def add_working_minutes(calendar: Calendar, start: datetime, minutes: int) -> datetime:
    """Add ``minutes`` of working time to ``start``, skipping non-working days/holidays.

    A result that exactly fills a working day lands on the day's close (e.g. 16:00), never
    rolling forward to the next day's open — so a predecessor finish and the successor start
    it drives share the same offset. This is the boundary-equivalence invariant the CPM
    engine relies on.
    """
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    day_open = calendar.day_start_minute
    day_close = day_open + calendar.hours_per_day * 60
    day, minute = _canonical(calendar, start.date(), _minute_of_day(start), day_open, day_close)
    remaining = minutes
    while remaining > 0:
        room = day_close - minute
        if remaining <= room:
            minute += remaining
            remaining = 0
        else:
            remaining -= room
            day = _next_working_day(calendar, day)
            minute = day_open
    return _at(day, minute)


def working_minutes_between(calendar: Calendar, start: datetime, end: datetime) -> int:
    """Count working minutes in the half-open interval from ``start`` to ``end``."""
    if end < start:
        raise ValueError("end must be >= start")
    day_open = calendar.day_start_minute
    day_close = day_open + calendar.hours_per_day * 60
    day, minute = _canonical(calendar, start.date(), _minute_of_day(start), day_open, day_close)
    end_date = end.date()
    end_minute = _minute_of_day(end)
    total = 0
    while (day, minute) < (end_date, end_minute):
        if not is_working_day(calendar, day) or minute >= day_close:
            day = _next_working_day(calendar, day)
            minute = day_open
            continue
        if day == end_date:
            limit = min(day_close, end_minute)
            if limit > minute:
                total += limit - minute
            break
        total += day_close - minute
        day = _next_working_day(calendar, day)
        minute = day_open
    return total
