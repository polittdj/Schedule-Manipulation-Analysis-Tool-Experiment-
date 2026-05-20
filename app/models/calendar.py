"""The working-time Calendar model."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Calendar(BaseModel):
    """A working-time calendar: which weekdays are worked, how many hours a working day
    holds, and which dates are holidays.

    The CPM engine uses a calendar to lay working time onto wall-clock dates. Collections
    are stored as **sorted tuples** (never sets): set iteration order is hash-seed
    dependent and would break byte-equal JSON round-trips.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    calendar_id: int
    name: str
    hours_per_day: int = Field(gt=0)
    working_weekdays: tuple[int, ...] = (1, 2, 3, 4, 5)
    holidays: tuple[date, ...] = ()
    day_start_minute: int = Field(default=480, ge=0, lt=1440)

    @field_validator("working_weekdays", mode="after")
    @classmethod
    def _normalize_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value:
            raise ValueError("working_weekdays must list at least one working day")
        for weekday in value:
            if not 1 <= weekday <= 7:
                raise ValueError(
                    f"working_weekdays entries must be ISO weekdays 1..7, got {weekday}"
                )
        return tuple(sorted(set(value)))

    @field_validator("holidays", mode="after")
    @classmethod
    def _normalize_holidays(cls, value: tuple[date, ...]) -> tuple[date, ...]:
        return tuple(sorted(set(value)))
