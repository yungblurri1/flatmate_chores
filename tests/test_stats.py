"""The slacking board's counting rules.

These pin the semantics that static/app.js mirrors client-side, so they are worth
keeping precise even though the browser is what actually draws the chart.
"""

from datetime import date

from app.rotation import Task, period_key_for
from app.stats import missed_by_person, progress_key

PEOPLE = ["A", "B", "C"]
TODAY = date(2024, 3, 6)  # a Wednesday

# Started long before the window under test, so it counts in every past week.
KITCHEN = Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=date(2024, 1, 1))


def test_every_past_week_counts_when_nothing_is_ticked():
    missed = missed_by_person(PEOPLE, [KITCHEN], set(), {}, "1w", today=TODAY)
    assert sum(missed.values()) == 1  # one chore, one elapsed week

    missed = missed_by_person(PEOPLE, [KITCHEN], set(), {}, "1m", today=TODAY)
    assert sum(missed.values()) == 4  # "last month" looks back four weeks


def test_the_current_open_week_is_never_counted():
    """You cannot be slacking on a week that has not finished yet."""
    missed = missed_by_person(PEOPLE, [KITCHEN], set(), {}, "1w", today=TODAY)
    this_week = period_key_for(TODAY, "weekly")
    # The only counted period is last week, so ticking this week changes nothing.
    ticked_now = {progress_key("kitchen", this_week)}
    assert missed_by_person(PEOPLE, [KITCHEN], ticked_now, {}, "1w", today=TODAY) == missed


def test_ticking_a_past_week_clears_it():
    last_week = period_key_for(date(2024, 2, 28), "weekly")
    done = {progress_key("kitchen", last_week)}
    assert sum(missed_by_person(PEOPLE, [KITCHEN], done, {}, "1w", today=TODAY).values()) == 0


def test_reassignment_moves_the_blame():
    plain = missed_by_person(PEOPLE, [KITCHEN], set(), {}, "1w", today=TODAY)
    blamed = next(p for p, n in plain.items() if n == 1)
    other = next(p for p in PEOPLE if p != blamed)

    last_week = period_key_for(date(2024, 2, 28), "weekly")
    moved = missed_by_person(
        PEOPLE, [KITCHEN], set(), {progress_key("kitchen", last_week): other}, "1w", today=TODAY
    )
    assert moved[blamed] == 0
    assert moved[other] == 1


def test_nothing_is_counted_before_a_chore_started():
    """The whole point of start dates: a new rota opens with a clean board."""
    fresh = Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=TODAY)
    missed = missed_by_person(PEOPLE, [fresh], set(), {}, "1y", today=TODAY)
    assert sum(missed.values()) == 0


def test_a_chore_counts_only_from_the_week_it_started():
    started = Task("kitchen", "Kitchen", "weekly", slot=0, starts_on=date(2024, 2, 21))
    # Elapsed weeks in range: 2/28 (counts) and 2/21 (counts); earlier ones do not.
    assert sum(missed_by_person(PEOPLE, [started], set(), {}, "1m", today=TODAY).values()) == 2


def test_oneoffs_count_only_in_their_own_week():
    last_week = period_key_for(date(2024, 2, 28), "weekly")
    oneoff = Task("guests", "Tidy", "weekly", slot=0, period_key=last_week)

    assert sum(missed_by_person(PEOPLE, [oneoff], set(), {}, "1m", today=TODAY).values()) == 1


def test_unknown_range_key_falls_back_to_the_default():
    fallback = missed_by_person(PEOPLE, [KITCHEN], set(), {}, "nonsense", today=TODAY)
    assert fallback == missed_by_person(PEOPLE, [KITCHEN], set(), {}, "1m", today=TODAY)
