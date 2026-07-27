"""Missed-chore counts per person, for the "who's slacking" board.

Assignments for past periods are recomputed the same way as the live roster --
rotation is a pure function of the date -- with any reassignments applied. Only
fully-elapsed periods count (not the current, still-open week/month), so nobody
gets dinged for a chore that isn't due yet.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import db
from .config import AppConfig
from .rotation import assignments_for

# key -> (label, completed weeks to look back, completed months to look back)
RANGE_OPTIONS = {
    "1w": {"label": "Last week", "weeks": 1, "months": 0},
    "1m": {"label": "Last month", "weeks": 4, "months": 1},
    "3m": {"label": "Last 3 months", "weeks": 13, "months": 3},
    "6m": {"label": "Last 6 months", "weeks": 26, "months": 6},
    "1y": {"label": "Last year", "weeks": 52, "months": 12},
}
DEFAULT_RANGE = "1m"


def _first_of_month_offset(today: date, months_ago: int) -> date:
    total = today.month - 1 - months_ago
    year = today.year + total // 12
    month = total % 12 + 1
    return date(year, month, 1)


def missed_by_person(config: AppConfig, range_key: str) -> dict[str, int]:
    """Return {person: count of assigned chores left undone} for the given range key."""
    option = RANGE_OPTIONS.get(range_key, RANGE_OPTIONS[DEFAULT_RANGE])
    today = date.today()

    past: dict[tuple[str, str], object] = {}

    for weeks_ago in range(1, option["weeks"] + 1):
        day = today - timedelta(weeks=weeks_ago)
        for a in assignments_for(day, config.people, config.tasks):
            if a.task.frequency == "weekly":
                past[(a.task.id, a.period_key)] = a

    for months_ago in range(1, option["months"] + 1):
        day = _first_of_month_offset(today, months_ago)
        for a in assignments_for(day, config.people, config.tasks):
            if a.task.frequency == "monthly":
                past[(a.task.id, a.period_key)] = a

    period_keys = sorted({key[1] for key in past})
    reassign_map = db.reassignment_map(period_keys)
    done_lookup = db.done_map(period_keys)

    missed = {p: 0 for p in config.people}
    for (task_id, period_key), a in past.items():
        if (task_id, period_key) in done_lookup:
            continue
        person = reassign_map.get((task_id, period_key), a.person)
        missed[person] = missed.get(person, 0) + 1

    return missed
