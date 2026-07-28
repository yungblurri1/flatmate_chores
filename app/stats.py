"""Missed-chore counts per person, for the "who's slacking" board.

Assignments for past periods are recomputed the same way as the live roster --
rotation is a pure function of the date -- with any reassignments applied. Only
fully-elapsed periods count (not the current, still-open week/month), so nobody
gets dinged for a chore that isn't due yet. A chore contributes nothing to periods
before its start date: the rota begins when it is set up, not retroactively.

The browser draws this chart from state it already holds, so `missed_by_person` is
mirrored in static/app.js rather than called over the wire. It stays here as the
reference implementation -- it is pure, so the tests pin these semantics for both.
"""

from __future__ import annotations

from datetime import date, timedelta

from .rotation import Task, assignments_for

# key -> (label, completed weeks to look back, completed months to look back)
RANGE_OPTIONS = {
    "1w": {"label": "Last week", "weeks": 1, "months": 0},
    "1m": {"label": "Last month", "weeks": 4, "months": 1},
    "3m": {"label": "Last 3 months", "weeks": 13, "months": 3},
    "6m": {"label": "Last 6 months", "weeks": 26, "months": 6},
    "1y": {"label": "Last year", "weeks": 52, "months": 12},
}
DEFAULT_RANGE = "1m"


def progress_key(task_id: str, period_key: str) -> str:
    """How a single chore-in-a-period is identified in the done/reassigned maps."""
    return f"{task_id}|{period_key}"


def _first_of_month_offset(today: date, months_ago: int) -> date:
    total = today.month - 1 - months_ago
    year = today.year + total // 12
    month = total % 12 + 1
    return date(year, month, 1)


def missed_by_person(
    people: list[str],
    tasks: list[Task],
    done: set[str],
    reassigned: dict[str, str],
    range_key: str,
    today: date | None = None,
) -> dict[str, int]:
    """Return {person: count of assigned chores left undone} for the given range."""
    option = RANGE_OPTIONS.get(range_key, RANGE_OPTIONS[DEFAULT_RANGE])
    today = today or date.today()

    past: dict[str, tuple[str, str]] = {}

    def collect(day: date, frequency: str) -> None:
        for a in assignments_for(day, people, tasks):
            if a.task.frequency == frequency:
                past[progress_key(a.task.id, a.period_key)] = (a.task.id, a.person)

    for weeks_ago in range(1, option["weeks"] + 1):
        collect(today - timedelta(weeks=weeks_ago), "weekly")

    for months_ago in range(1, option["months"] + 1):
        collect(_first_of_month_offset(today, months_ago), "monthly")

    missed = {p: 0 for p in people}
    for key, (_, person) in past.items():
        if key in done:
            continue
        person = reassigned.get(key, person)
        if person in missed:
            missed[person] += 1

    return missed
