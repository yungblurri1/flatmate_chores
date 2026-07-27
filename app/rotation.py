"""Deterministic chore rotation.

The whole rotation is a pure function of the date. There is no scheduler and no
stored assignment table: given a date, the people, and the tasks, we can always
recompute who does what. That keeps the app stateless where it matters and makes
the logic trivial to unit-test.

Weekly tasks rotate every ISO week, monthly tasks rotate every calendar month.
Within a single period the tasks are spread across people by offsetting each task,
so two people rarely get everything in the same week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# A fixed Monday used as the origin for week counting. 2024-01-01 was a Monday.
_EPOCH_MONDAY = date(2024, 1, 1)
_EPOCH_YEAR = 2024
_EPOCH_MONTH = 1


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    frequency: str  # "weekly" or "monthly"
    description: str = ""


@dataclass(frozen=True)
class Assignment:
    task: Task
    person: str
    period_key: str  # e.g. "W-123" or "M-45"; scopes completion to this period


def week_index(day: date) -> int:
    """Monotonic week counter. Increases by 1 every Monday."""
    monday = day - timedelta(days=day.weekday())
    return (monday - _EPOCH_MONDAY).days // 7


def month_index(day: date) -> int:
    """Monotonic month counter. Increases by 1 on the 1st of each month."""
    return (day.year - _EPOCH_YEAR) * 12 + (day.month - _EPOCH_MONTH)


def week_bounds(day: date) -> tuple[date, date]:
    """Return the Monday and Sunday of the ISO week containing `day`."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def assignments_for(day: date, people: list[str], tasks: list[Task]) -> list[Assignment]:
    """Compute the full list of assignments active on `day`.

    People are assigned round-robin by period index plus the task's position in
    its frequency group, so the load spreads out instead of piling on one person.
    """
    if not people:
        return []

    n = len(people)
    wi = week_index(day)
    mi = month_index(day)

    weekly = [t for t in tasks if t.frequency == "weekly"]
    monthly = [t for t in tasks if t.frequency == "monthly"]

    result: list[Assignment] = []

    for i, task in enumerate(weekly):
        person = people[(wi + i) % n]
        result.append(Assignment(task=task, person=person, period_key=f"W-{wi}"))

    for i, task in enumerate(monthly):
        person = people[(mi + i) % n]
        result.append(Assignment(task=task, person=person, period_key=f"M-{mi}"))

    return result
