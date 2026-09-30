"""When a week's deadline falls, and which games it puts in reach.

All the times here are written in UTC with the Eastern clock noted, because Sunday is
decided on the Eastern clock and the conversion is easy to get backwards.
"""

from datetime import UTC, datetime

import pytest

from app.integrations.espn import (
    NflEvent,
    WeekSchedule,
    is_monday_kickoff,
    is_sunday_kickoff,
)
from app.models import League, NflWeek
from app.services import rounds

# Week 4 of 2026, which carries every slot a league might care about -- including the
# international morning game that six of this season's weeks have.
THU = datetime(2026, 9, 18, 0, 15, tzinfo=UTC)  # Thu 8:15pm ET
MORNING = datetime(2026, 9, 20, 13, 30, tzinfo=UTC)  # Sun 9:30am ET, abroad
AFTERNOON = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)  # Sun 1:00pm ET
LATE = datetime(2026, 9, 20, 20, 5, tzinfo=UTC)  # Sun 4:05pm ET
SNF = datetime(2026, 9, 21, 0, 20, tzinfo=UTC)  # Sun 8:20pm ET
MNF = datetime(2026, 9, 22, 0, 15, tzinfo=UTC)  # Mon 8:15pm ET


def event(event_id: str, kickoff: datetime, *teams: str) -> NflEvent:
    return NflEvent(event_id, " @ ".join(teams), kickoff, "STATUS_SCHEDULED", teams)


def week(*events: NflEvent) -> WeekSchedule:
    return WeekSchedule(season="2026", week=4, events=list(events))


FULL_WEEK = week(
    event("t", THU, "BUF", "MIA"),
    event("i", MORNING, "IND", "WSH"),
    event("a", AFTERNOON, "PHI", "KC"),
    event("d", LATE, "SF", "SEA"),
    event("s", SNF, "DAL", "NYG"),
    event("m", MNF, "CIN", "CLE"),
)


# ------------------------------------------------------------------ what counts as Sunday


@pytest.mark.parametrize(
    ("kickoff", "sunday"),
    [
        (THU, False),
        (MORNING, True),
        (AFTERNOON, True),
        # 4:05pm Eastern is already Monday in UTC, which is exactly why the check is done
        # on the Eastern clock.
        (LATE, True),
        (SNF, True),
        # Monday night is Monday, whatever time it starts.
        (MNF, False),
    ],
)
def test_which_kickoffs_are_sunday(kickoff, sunday):
    assert is_sunday_kickoff(kickoff) is sunday


def test_only_monday_night_is_monday():
    assert is_monday_kickoff(MNF)
    assert not any(is_monday_kickoff(k) for k in (THU, MORNING, AFTERNOON, LATE, SNF))


def test_monday_football_starts_with_the_nightcap():
    assert FULL_WEEK.monday_kickoff_at == MNF


def test_a_week_with_no_monday_game_has_no_upper_bound():
    assert week(event("a", AFTERNOON, "PHI", "KC")).monday_kickoff_at is None


def test_the_window_opens_with_the_first_sunday_game():
    """The morning game abroad counts, so it opens three and a half hours before the slate."""
    assert FULL_WEEK.sunday_kickoff_at == MORNING


def test_a_week_with_no_morning_game_opens_with_the_slate():
    quiet = week(event("t", THU, "BUF", "MIA"), event("a", AFTERNOON, "PHI", "KC"))
    assert quiet.sunday_kickoff_at == AFTERNOON


def test_the_window_survives_the_clocks_going_back():
    """1pm Eastern is 17:00 UTC on EDT and 18:00 UTC on EST. Both are Sunday."""
    december = datetime(2026, 12, 20, 18, 0, tzinfo=UTC)  # Sun 1:00pm EST
    assert is_sunday_kickoff(december)
    assert week(event("x", december, "GB", "CHI")).sunday_kickoff_at == december


def test_a_week_with_no_sunday_games_has_no_window():
    assert week(event("t", THU, "BUF", "MIA")).sunday_kickoff_at is None


# ------------------------------------------------------------- which kickoff we count back from


def league(mode: str) -> League:
    row = League(sleeper_league_id="L1", season="2026", name="Test", deadline_mode=mode)
    # Column defaults land at flush, not at construction, so an in-memory League has None
    # here where a stored one has true. Set it to match what comes back from the database.
    row.allow_monday = True
    return row


def cached(sunday: datetime | None, monday: datetime | None = MNF) -> NflWeek:
    return NflWeek(
        season="2026",
        week=4,
        first_kickoff_at=THU,
        last_kickoff_at=MNF,
        sunday_kickoff_at=sunday,
        monday_kickoff_at=monday,
    )


def no_monday(mode: str = rounds.DEADLINE_FIRST_KICKOFF) -> League:
    league = League(sleeper_league_id="L1", season="2026", name="Test", deadline_mode=mode)
    league.allow_monday = False
    return league


def test_the_default_deadline_is_the_first_kickoff_of_the_week():
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_FIRST_KICKOFF), cached(MORNING))
    assert anchor == THU


def test_a_sunday_league_counts_back_from_the_first_sunday_game():
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_SUNDAY), cached(MORNING))
    assert anchor == MORNING


def test_a_sunday_league_falls_back_to_the_first_kickoff_with_no_sunday_game():
    """Locking early is the safe way to be wrong: late would take legs after kickoff."""
    anchor = rounds.deadline_anchor(league(rounds.DEADLINE_SUNDAY), cached(None))
    assert anchor == THU


# ------------------------------------------------------------------ which games are in reach


def test_the_default_puts_no_game_out_of_reach():
    assert rounds.window_opens(league(rounds.DEADLINE_FIRST_KICKOFF), cached(MORNING)) is None


def test_a_sunday_league_restricts_to_the_window():
    assert rounds.window_opens(league(rounds.DEADLINE_SUNDAY), cached(MORNING)) == MORNING


def test_no_sunday_game_means_no_restriction_rather_than_no_legs():
    assert rounds.window_opens(league(rounds.DEADLINE_SUNDAY), cached(None)) is None


# ------------------------------------------------------------------ keeping Monday out


def test_monday_is_in_reach_by_default():
    assert rounds.window_closes(league(rounds.DEADLINE_FIRST_KICKOFF), cached(MORNING)) is None


def test_turning_monday_off_closes_the_window_at_the_nightcap():
    assert rounds.window_closes(no_monday(), cached(MORNING)) == MNF


def test_a_week_with_no_monday_game_closes_nothing():
    assert rounds.window_closes(no_monday(), cached(MORNING, monday=None)) is None


def test_turning_monday_off_does_not_move_the_lock():
    """The two settings are independent: one narrows the slate, the other moves the deadline."""
    assert rounds.deadline_anchor(no_monday(), cached(MORNING)) == THU
    assert rounds.deadline_anchor(no_monday(rounds.DEADLINE_SUNDAY), cached(MORNING)) == MORNING


def test_an_unset_monday_setting_allows_monday():
    """An in-memory League has None here. Unset must read as the default, never as blocked."""
    unset = League(sleeper_league_id="L1", season="2026", name="Test", deadline_mode="sunday")
    assert unset.allow_monday is None
    assert rounds.window_closes(unset, cached(MORNING)) is None
