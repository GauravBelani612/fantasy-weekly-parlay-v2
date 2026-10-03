"""Turning a week's scoreboard into the matchup list the league sees.

Nothing upstream reports a bye, so they are worked out by subtracting whoever is playing
from all 32 teams -- which means a short scoreboard would read as half the NFL resting.
"""

from datetime import UTC, datetime

from app.integrations.espn import NflEvent, TeamRef, WeekSchedule
from app.serializers import week_schedule_out

KICK = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 12, 0, 15, tzinfo=UTC)

ALL_TEAMS = {
    abbr: TeamRef(abbr, f"{abbr} Team", f"https://logos.example/{abbr.lower()}.png")
    for abbr in ("PHI", "KC", "CIN", "JAX", "DAL", "NYG", "SEA", "ARI")
}


def game(event_id: str, away: str, home: str, kickoff: datetime = KICK) -> NflEvent:
    return NflEvent(
        event_id=event_id,
        name=f"{away} @ {home}",
        kickoff_at=kickoff,
        status="STATUS_SCHEDULED",
        teams=(away, home),
        competitors=(ALL_TEAMS[away], ALL_TEAMS[home]),
    )


def week(*events: NflEvent) -> WeekSchedule:
    return WeekSchedule(season="2026", week=5, events=list(events))


FOUR_GAMES = week(
    game("1", "PHI", "KC"),
    game("2", "CIN", "JAX"),
    game("3", "DAL", "NYG"),
    game("4", "SEA", "ARI", LATER),
)


# ------------------------------------------------------------------ the games


def test_games_come_back_in_kickoff_order():
    out = week_schedule_out(
        week(game("late", "SEA", "ARI", LATER), game("early", "PHI", "KC")), ALL_TEAMS
    )
    assert [g.event_id for g in out.games] == ["early", "late"]


def test_each_game_carries_both_teams_with_their_crests():
    out = week_schedule_out(FOUR_GAMES, ALL_TEAMS)
    first = out.games[0]
    assert (first.away.abbreviation, first.home.abbreviation) == ("PHI", "KC")
    assert first.away.logo_url == "https://logos.example/phi.png"


# ------------------------------------------------------------------ the byes


def test_whoever_is_not_playing_is_on_bye():
    out = week_schedule_out(week(game("1", "PHI", "KC"), game("2", "CIN", "JAX")), ALL_TEAMS)
    assert [t.abbreviation for t in out.byes] == ["ARI", "DAL", "NYG", "SEA"]


def test_a_bye_team_carries_its_name_and_crest():
    out = week_schedule_out(week(game("1", "PHI", "KC")), ALL_TEAMS)
    resting = {t.abbreviation: t for t in out.byes}
    assert resting["CIN"].name == "CIN Team"
    assert resting["CIN"].logo_url == "https://logos.example/cin.png"


def test_a_full_week_has_nobody_on_bye():
    assert week_schedule_out(FOUR_GAMES, ALL_TEAMS).byes == []


def test_a_scoreboard_that_came_back_short_reports_no_byes():
    """One game out of four would mean six teams resting. That is a bad fetch, not a bye."""
    out = week_schedule_out(week(game("1", "PHI", "KC")), ALL_TEAMS)
    assert len(out.byes) == 6, "six is still plausible, so these are reported"

    narrow = dict(ALL_TEAMS, **{f"T{i}": TeamRef(f"T{i}", f"T{i}", None) for i in range(4)})
    assert week_schedule_out(week(game("1", "PHI", "KC")), narrow).byes == [], (
        "ten resting teams is not a bye week"
    )


def test_no_team_list_means_no_byes_rather_than_no_schedule():
    """The team list is a second fetch. Losing it must not cost the games."""
    out = week_schedule_out(FOUR_GAMES)
    assert out.byes == []
    assert len(out.games) == 4
