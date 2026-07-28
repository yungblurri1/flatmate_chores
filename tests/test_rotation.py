from datetime import date, timedelta

from app.rotation import (
    Task,
    assignments_for,
    month_index,
    period_key_for,
    slot_for_starter,
    week_bounds,
    week_index,
)

PEOPLE = ["A", "B", "C"]
TASKS = [
    Task("kitchen", "Kitchen", "weekly", slot=0),
    Task("bath", "Bathroom", "weekly", slot=1),
    Task("windows", "Windows", "monthly", slot=0),
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


def test_deleting_a_task_leaves_other_assignments_untouched():
    """The point of Task.slot: removing a chore must not re-shuffle the rest.

    If the rotation offset were the task's index in the list, deleting "kitchen"
    would shift "bath" onto a different person -- retroactively, for every past
    week the slacking board scores.
    """
    d = date(2024, 1, 1)
    before = {a.task.id: a.person for a in assignments_for(d, PEOPLE, TASKS)}
    remaining = [t for t in TASKS if t.id != "kitchen"]

    for a in assignments_for(d, PEOPLE, remaining):
        assert a.person == before[a.task.id]


def test_added_task_takes_the_next_free_slot():
    d = date(2024, 1, 1)
    added = Task("plants", "Water the plants", "weekly", slot=2)
    weekly = [a for a in assignments_for(d, PEOPLE, TASKS + [added]) if a.task.frequency == "weekly"]

    assert len({a.person for a in weekly}) == 3  # still one chore each, no doubling up


# ----------------------------------------------------------------- start dates

def test_task_does_not_exist_before_its_start_date():
    start = date(2024, 3, 4)  # a Monday
    task = Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=start)

    assert assignments_for(start - timedelta(days=7), PEOPLE, [task]) == []
    assert len(assignments_for(start, PEOPLE, [task])) == 1
    assert len(assignments_for(start + timedelta(days=7), PEOPLE, [task])) == 1


def test_start_date_counts_the_whole_period_it_falls_in():
    """A chore created mid-week belongs to that week, not from the next one."""
    wednesday = date(2024, 3, 6)
    task = Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=wednesday)

    monday = date(2024, 3, 4)
    assert len(assignments_for(monday, PEOPLE, [task])) == 1
    assert assignments_for(monday - timedelta(days=1), PEOPLE, [task]) == []


def test_monthly_start_date_uses_month_boundaries():
    task = Task("windows", "Windows", "monthly", slot=0, starts_on=date(2024, 3, 15))

    assert assignments_for(date(2024, 3, 1), PEOPLE, [task]) != []
    assert assignments_for(date(2024, 2, 29), PEOPLE, [task]) == []


# -------------------------------------------------------------------- one-offs

def test_oneoff_appears_only_in_its_own_period():
    d = date(2024, 3, 6)
    key = period_key_for(d, "weekly")
    task = Task("guests", "Tidy for guests", "weekly", slot=0, period_key=key)

    assert len(assignments_for(d, PEOPLE, [task])) == 1
    assert assignments_for(d + timedelta(days=7), PEOPLE, [task]) == []
    assert assignments_for(d - timedelta(days=7), PEOPLE, [task]) == []


def test_oneoff_does_not_shift_the_recurring_chores():
    d = date(2024, 3, 6)
    before = {a.task.id: a.person for a in assignments_for(d, PEOPLE, TASKS)}
    oneoff = Task("guests", "Tidy", "weekly", slot=2, period_key=period_key_for(d, "weekly"))

    for a in assignments_for(d, PEOPLE, TASKS + [oneoff]):
        if a.task.id != "guests":
            assert a.person == before[a.task.id]


# --------------------------------------------------------------- who starts it

def test_slot_for_starter_puts_the_chosen_person_on_it():
    d = date(2024, 3, 6)
    for starter in PEOPLE:
        slot = slot_for_starter(d, "weekly", PEOPLE, starter)
        task = Task("x", "X", "weekly", slot=slot)
        assert assignments_for(d, PEOPLE, [task])[0].person == starter


def test_slot_for_starter_still_rotates_afterwards():
    d = date(2024, 3, 6)
    slot = slot_for_starter(d, "weekly", PEOPLE, "C")
    task = Task("x", "X", "weekly", slot=slot)

    assert assignments_for(d, PEOPLE, [task])[0].person == "C"
    assert assignments_for(d + timedelta(days=7), PEOPLE, [task])[0].person == "A"


def test_slot_for_starter_handles_monthly_and_unknown_people():
    d = date(2024, 3, 6)
    slot = slot_for_starter(d, "monthly", PEOPLE, "B")
    assert assignments_for(d, PEOPLE, [Task("x", "X", "monthly", slot=slot)])[0].person == "B"

    assert slot_for_starter(d, "weekly", PEOPLE, "Nobody") == 0
    assert slot_for_starter(d, "weekly", [], "A") == 0
