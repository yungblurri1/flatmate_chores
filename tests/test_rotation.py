from datetime import date, timedelta

from app.rotation import (
    Task,
    assignments_for,
    month_index,
    week_bounds,
    week_index,
)

PEOPLE = ["A", "B", "C"]
TASKS = [
    Task("kitchen", "Kitchen", "weekly"),
    Task("bath", "Bathroom", "weekly"),
    Task("windows", "Windows", "monthly"),
]


def test_week_index_advances_by_one_each_week():
    d = date(2024, 1, 1)  # Monday
    assert week_index(d) == 0
    assert week_index(d + timedelta(days=6)) == 0   # same ISO week
    assert week_index(d + timedelta(days=7)) == 1   # next Monday


def test_month_index_advances_each_month():
    assert month_index(date(2024, 1, 15)) == 0
    assert month_index(date(2024, 2, 1)) == 1
    assert month_index(date(2025, 1, 1)) == 12


def test_week_bounds_returns_monday_to_sunday():
    monday, sunday = week_bounds(date(2024, 3, 6))  # a Wednesday
    assert monday == date(2024, 3, 4)
    assert sunday == date(2024, 3, 10)


def test_weekly_assignment_rotates_between_weeks():
    d = date(2024, 1, 1)
    a1 = assignments_for(d, PEOPLE, TASKS)
    a2 = assignments_for(d + timedelta(days=7), PEOPLE, TASKS)
    kitchen1 = next(a for a in a1 if a.task.id == "kitchen")
    kitchen2 = next(a for a in a2 if a.task.id == "kitchen")
    assert kitchen1.person != kitchen2.person


def test_weekly_tasks_spread_across_people_same_week():
    d = date(2024, 1, 1)
    weekly = [a for a in assignments_for(d, PEOPLE, TASKS) if a.task.frequency == "weekly"]
    people = {a.person for a in weekly}
    assert len(people) == len(weekly)  # different people for each weekly task


def test_period_key_scopes_completion():
    d = date(2024, 1, 1)
    a = assignments_for(d, PEOPLE, TASKS)
    keys = {x.task.id: x.period_key for x in a}
    assert keys["kitchen"].startswith("W-")
    assert keys["windows"].startswith("M-")


def test_empty_people_yields_no_assignments():
    assert assignments_for(date.today(), [], TASKS) == []
