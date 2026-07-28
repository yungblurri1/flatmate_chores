"""Deterministic chore rotation.

The whole rotation is a pure function of the date. There is no scheduler and no
stored assignment table: given a date, the people, and the tasks, we can always
recompute who does what. That keeps the app stateless where it matters and makes
the logic trivial to unit-test.

Weekly tasks rotate every ISO week, monthly tasks rotate every calendar month.
Within a single period the tasks are spread across people by offsetting each task,
so two people rarely get everything in the same week.

That per-task offset is `Task.slot`, stored alongside the task rather than derived
from its position in the list. Deleting a chore therefore leaves every other
chore's history untouched -- if the offset were the list index, removing one task
would silently re-shuffle who was responsible for all the tasks after it, in every
past week the slacking board looks at.
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
    slot: int = 0  # stable rotation offset within this task's frequency group
    # None for a recurring chore. Set to a single period ("W-123" / "M-45") for a
    # one-off added to just that week or month, which never returns afterwards.
    period_key: str | None = None
    # The chore does not exist in any period before this date, so the slacking
    # board never blames anyone for weeks that predate the chore itself.
    starts_on: date | None = None

    @property
    def is_oneoff(self) -> bool:
        return self.period_key is not None


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


def period_key_for(day: date, frequency: str) -> str:
    """The period a chore of this frequency belongs to on `day`."""
    if frequency == "weekly":
        return f"W-{week_index(day)}"
    return f"M-{month_index(day)}"


def slot_for_starter(day: date, frequency: str, people: list[str], starter: str) -> int:
    """The slot that puts `starter` on this chore in the period containing `day`.

    Inverts the assignment formula: person = people[(period_index + slot) % n].
    """
    if not people or starter not in people:
        return 0
    period_index = week_index(day) if frequency == "weekly" else month_index(day)
    return (people.index(starter) - period_index) % len(people)


def week_bounds(day: date) -> tuple[date, date]:
    """Return the Monday and Sunday of the ISO week containing `day`."""
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def assignments_for(day: date, people: list[str], tasks: list[Task]) -> list[Assignment]:
    """Compute the full list of assignments active on `day`.

    People are assigned round-robin by period index plus the task's slot, so the
    load spreads out instead of piling on one person.
    """
    if not people:
        return []

    n = len(people)
    wi = week_index(day)
    mi = month_index(day)

    result: list[Assignment] = []

    for task in tasks:
        weekly = task.frequency == "weekly"
        period_index = wi if weekly else mi
        period_key = period_key_for(day, task.frequency)

        # A one-off belongs to exactly one period and is simply absent from every
        # other one; callers normally filter these out before we get here.
        if task.is_oneoff and task.period_key != period_key:
            continue

        # Nothing exists before the chore did.
        if task.starts_on is not None:
            start = task.starts_on
            if period_index < (week_index(start) if weekly else month_index(start)):
                continue

        person = people[(period_index + task.slot) % n]
        result.append(Assignment(task=task, person=person, period_key=period_key))

    return result
