"""Turning a week's scoreboard into the matchup list the league sees.

Nothing upstream reports a bye, so they are worked out by subtracting whoever is playing
from all 32 teams -- which means a short scoreboard would read as half the NFL resting.
"""

from datetime import UTC, datetime

from app.integrations.espn import NflEvent, TeamRef, WeekSchedule
from app.serializers import week_schedule_out

KICK = datetime(2026, 10, 11, 17, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 12, 0, 15, tzinfo=UTC)

RECORDS = {
    "PHI": "4-0", "KC": "3-1", "CIN": "2-2", "JAX": "1-3",
    "DAL": "2-1-1", "NYG": "0-4", "SEA": "3-1", "ARI": "2-2",
}

# The standings are the only thing that reports a record, and they are also where the bye
# teams' names and crests come from -- so one map carries all three.
ALL_TEAMS = {
    abbr: TeamRef(abbr, f"{abbr} Team", f"https://logos.example/{abbr.lower()}.png", record)
    for abbr, record in RECORDS.items()
}


def game(event_id: str, away: str, home: str, kickoff: datetime = KICK) -> NflEvent:
    return NflEvent(
        event_id=event_id,
        name=f"{away} @ {home}",
        kickoff_at=kickoff,
        status="STATUS_SCHEDULED",
        teams=(away, home),
        # Built the way the scoreboard builds them: name and crest, but no record.
        competitors=(
            TeamRef(away, f"{away} Team", f"https://logos.example/{away.lower()}.png"),
            TeamRef(home, f"{home} Team", f"https://logos.example/{home.lower()}.png"),
        ),
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


# ------------------------------------------------------------------ the records


def test_a_games_teams_pick_up_their_records_from_the_standings():
    """The scoreboard does not carry a record, so it is looked up for every row alike."""
    out = week_schedule_out(FOUR_GAMES, ALL_TEAMS)
    shown = {g.away.abbreviation: g.away.record for g in out.games}
    assert shown["PHI"] == "4-0"
    assert shown["DAL"] == "2-1-1", "a tie is three parts, not two"


def test_a_bye_team_carries_its_own_record():
    out = week_schedule_out(week(game("1", "PHI", "KC")), ALL_TEAMS)
    assert {t.abbreviation: t.record for t in out.byes}["NYG"] == "0-4"


def test_a_team_the_standings_never_mentioned_has_no_record():
    """Null, not a guess and not an empty string the UI would render as "()"."""
    out = week_schedule_out(FOUR_GAMES, {})
    assert all(g.away.record is None and g.home.record is None for g in out.games)


def test_losing_the_standings_costs_the_records_but_not_the_games():
    out = week_schedule_out(FOUR_GAMES)
    assert len(out.games) == 4
    assert out.games[0].away.name == "PHI Team"
    assert out.games[0].away.record is None
