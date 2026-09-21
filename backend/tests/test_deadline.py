"""When a week's deadline falls, and which games it puts in reach.

All the times here are written in UTC with the Eastern clock noted, because that is the
conversion the RedZone window turns on and it is easy to get backwards.
"""

from datetime import UTC, datetime

import pytest

from app.integrations.espn import NflEvent, WeekSchedule, in_redzone_window
from app.models import League, NflWeek
from app.services import rounds

# Week 3 of 2026, carrying every slot a league might want to exclude.
THU = datetime(2026, 9, 18, 0, 15, tzinfo=UTC)  # Thu 8:15pm ET
LONDON = datetime(2026, 9, 20, 13, 30, tzinfo=UTC)  # Sun 9:30am ET
REDZONE = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)  # Sun 1:00pm ET
LATE = datetime(2026, 9, 20, 20, 5, tzinfo=UTC)  # Sun 4:05pm ET
SNF = datetime(2026, 9, 21, 0, 20, tzinfo=UTC)  # Sun 8:20pm ET
MNF = datetime(2026, 9, 22, 0, 15, tzinfo=UTC)  # Mon 8:15pm ET


def event(event_id: str, kickoff: datetime, *teams: str) -> NflEvent:
    return NflEvent(event_id, " @ ".join(teams), kickoff, "STATUS_SCHEDULED", teams)


def week(*events: NflEvent) -> WeekSchedule:
    return WeekSchedule(season="2026", week=3, events=list(events))


FULL_WEEK = week(
    event("t", THU, "BUF", "MIA"),
    event("l", LONDON, "JAX", "ATL"),
    event("r", REDZONE, "PHI", "KC"),
    event("d", LATE, "SF", "SEA"),
    event("s", SNF, "DAL", "NYG"),
    event("m", MNF, "CIN", "CLE"),
)


# ------------------------------------------------------------------ what counts as RedZone


@pytest.mark.parametrize(
    ("kickoff", "inside"),
    [
        (THU, False),
        # The international morning game is the one people forget: it is Sunday, but it
        # kicks off three and a half hours before RedZone goes on air.
        (LONDON, False),
        (REDZONE, True),
        (LATE, True),
        (SNF, True),
        # Monday night is Monday, whatever time it starts.
        (MNF, False),
    ],
)
def test_which_kickoffs_are_in_the_window(kickoff, inside):
    assert in_redzone_window(kickoff) is inside


def test_the_window_opens_with_the_first_afternoon_game():
    assert FULL_WEEK.redzone_kickoff_at == REDZONE


def test_the_window_survives_the_clocks_going_back():
    """1pm Eastern is 17:00 UTC on EDT and 18:00 UTC on EST. Both are 1pm."""
    december = datetime(2026, 12, 20, 18, 0, tzinfo=UTC)  # Sun 1:00pm EST
    assert in_redzone_window(december)
    assert week(event("x", december, "GB", "CHI")).redzone_kickoff_at == december


def test_a_week_with_no_afternoon_games_has_no_window():
    assert week(event("t", THU, "BUF", "MIA")).redzone_kickoff_at is None


# ------------------------------------------------------------- which kickoff we count back from


def league(mode: str) -> League:
    return League(sleeper_league_id="L1", season="2026", name="Test", deadline_mode=mode)


def cached(redzone: datetime | None) -> NflWeek:
    return NflWeek(
        season="2026", week=3, first_kickoff_at=THU, last_kickoff_at=MNF, redzone_kickoff_at=redzone
    )


def test_the_default_deadline_is_the_first_kickoff_of_the_week():
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_FIRST_KICKOFF), cached(REDZONE))
    assert anchor == THU


def test_a_redzone_league_counts_back_from_sunday_afternoon():
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_SUNDAY_REDZONE), cached(REDZONE))
    assert anchor == REDZONE


def test_a_redzone_league_falls_back_to_the_first_kickoff_with_no_window():
    """Locking early is the safe way to be wrong: late would take legs after kickoff."""
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_SUNDAY_REDZONE), cached(None))
    assert anchor == THU


# ------------------------------------------------------------------ which games are in reach


def test_the_default_puts_no_game_out_of_reach():
    assert rounds.window_opens(league(rounds.DEADLINE_FIRST_KICKOFF), cached(REDZONE)) is None


def test_a_redzone_league_restricts_to_the_window():
    assert rounds.window_opens(league(rounds.DEADLINE_SUNDAY_REDZONE), cached(REDZONE)) == REDZONE


def test_no_window_means_no_restriction_rather_than_no_legs():
    assert rounds.window_opens(league(rounds.DEADLINE_SUNDAY_REDZONE), cached(None)) is None
