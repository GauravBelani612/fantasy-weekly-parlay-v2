"""Why a leg gets turned away.

One slip, one opinion per thing -- and, for a league betting from RedZone on, nothing that
has already kicked off by the time the window opens.
"""

from datetime import UTC, datetime

from app.integrations.espn import NflEvent, WeekSchedule
from app.models import Leg
from app.services import leg_rules

KICK = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)

# Two games, so "a different game" is a thing the tests can say. SEA and ARI are in neither.
SCHEDULE = WeekSchedule(
    season="2026",
    week=3,
    events=[
        NflEvent("1", "PHI @ KC", KICK, "STATUS_SCHEDULED", ("PHI", "KC")),
        NflEvent("2", "CIN @ JAX", KICK, "STATUS_SCHEDULED", ("CIN", "JAX")),
    ],
)


def rushing(
    subject: str, direction: str = "over", line: float = 50.5, team: str = "PHI"
) -> dict:
    return {
        "understood": True,
        "market": "rushing_yards",
        "subject": subject,
        "team": team,
        "direction": direction,
        "line": line,
    }


def anytime_td(subject: str) -> dict:
    return {
        "understood": True,
        "market": "touchdowns",
        "subject": subject,
        "team": "PHI",
        "direction": "at_least",
        "line": 1,
    }


def team_bet(market: str, team: str, direction: str | None = None, line: float | None = None):
    return {
        "understood": True,
        "market": market,
        "subject": None,
        "team": team,
        "direction": direction,
        "line": line,
    }


def board(*parsed: dict | None) -> list[Leg]:
    """Legs already in the round."""
    return [Leg(raw_text=f"leg {i}", parsed=p) for i, p in enumerate(parsed)]


def clashes(new: dict | None, *existing: dict | None) -> bool:
    return leg_rules.find(new, SCHEDULE, board(*existing)) is not None


# ------------------------------------------------------------------ one bet per player stat


def test_the_other_side_of_the_same_stat_is_refused():
    assert clashes(rushing("Saquon Barkley", "under"), rushing("Saquon Barkley", "over"))


def test_a_softer_version_of_the_same_stat_is_refused():
    """Over 30 is nearly free once over 50 is on the slip. One opinion, bet twice."""
    assert clashes(rushing("Saquon Barkley", "over", 30.5), rushing("Saquon Barkley", "over", 50.5))


def test_a_greedier_version_of_the_same_stat_is_refused():
    assert clashes(rushing("Saquon Barkley", "over", 70.5), rushing("Saquon Barkley", "over", 50.5))


def test_a_different_stat_for_the_same_player_is_allowed():
    """Saquon's yards and Saquon's touchdowns are genuinely different bets."""
    assert not clashes(anytime_td("Saquon Barkley"), rushing("Saquon Barkley"))


def test_a_different_player_is_allowed():
    assert not clashes(rushing("Jahmyr Gibbs"), rushing("Saquon Barkley"))


def test_a_name_is_matched_however_it_was_typed():
    assert clashes(rushing("jamarr chase"), rushing("Ja'Marr Chase"))


# ------------------------------------------------------------------ one bet per game


def test_the_same_moneyline_twice_is_refused():
    assert clashes(team_bet("moneyline", "KC"), team_bet("moneyline", "KC"))


def test_the_opposite_moneyline_in_the_same_game_is_refused():
    """PHI @ KC cannot have both sides: one of them is guaranteed to sink the slip."""
    assert clashes(team_bet("moneyline", "PHI"), team_bet("moneyline", "KC"))


def test_a_spread_against_a_moneyline_in_the_same_game_is_refused():
    assert clashes(team_bet("spread", "PHI", line=3.5), team_bet("moneyline", "KC"))


def test_a_moneyline_in_another_game_is_allowed():
    assert not clashes(team_bet("moneyline", "CIN"), team_bet("moneyline", "KC"))


def test_both_sides_of_a_game_total_is_refused():
    assert clashes(
        team_bet("game_total", "KC", "under", 47.5), team_bet("game_total", "PHI", "over", 47.5)
    )


def test_another_games_total_is_allowed():
    assert not clashes(
        team_bet("game_total", "CIN", "over", 41.5), team_bet("game_total", "KC", "over", 47.5)
    )


def test_the_same_team_total_twice_is_refused():
    assert clashes(
        team_bet("team_total", "KC", "under", 24.5), team_bet("team_total", "KC", "over", 24.5)
    )


def test_the_opponents_team_total_is_allowed():
    """Both teams going over is not a contradiction -- it is a shootout."""
    assert not clashes(
        team_bet("team_total", "PHI", "over", 21.5), team_bet("team_total", "KC", "over", 24.5)
    )


# ------------------------------------------------------------------ when it cannot tell


def test_a_team_not_on_the_schedule_still_blocks_its_own_duplicate():
    """No game to group by, so fall back to the team: catch the repeat, allow the rest."""
    assert clashes(team_bet("moneyline", "SEA"), team_bet("moneyline", "SEA"))
    assert not clashes(team_bet("moneyline", "ARI"), team_bet("moneyline", "SEA"))


def test_a_leg_nobody_has_read_yet_blocks_nothing():
    """Refusing a legal bet because the parser was down is the worse failure."""
    assert not clashes(rushing("Saquon Barkley"), None)


def test_an_unreadable_leg_blocks_nothing():
    assert not clashes(rushing("Saquon Barkley"), {"understood": False, "note": "no idea"})


def test_an_unreadable_leg_is_never_itself_refused():
    assert not clashes({"understood": False}, rushing("Saquon Barkley"))


def test_no_schedule_at_all_still_blocks_a_repeat():
    legs = board(team_bet("moneyline", "KC"))
    assert leg_rules.find(team_bet("moneyline", "KC"), None, legs) is not None
    assert leg_rules.find(team_bet("moneyline", "PHI"), None, legs) is None


# ------------------------------------------------------------------ what it says


def test_the_refusal_names_the_person_and_their_leg():
    legs = [Leg(raw_text="Saquon over 50 rush yds", parsed=rushing("Saquon Barkley"))]
    clash = leg_rules.find(rushing("Saquon Barkley", "under"), SCHEDULE, legs)
    assert clash is not None
    message = clash.message("Byju")
    assert 'Byju already has "Saquon over 50 rush yds"' in message
    assert "one bet per player per stat" in message


# ------------------------------------------------------------- betting from RedZone onward

# The same week the deadline tests use: a Thursday game, an international Sunday morning
# one, and the afternoon window RedZone leagues actually want.
THU = datetime(2026, 9, 18, 0, 15, tzinfo=UTC)  # Thu 8:15pm ET
LONDON = datetime(2026, 9, 20, 13, 30, tzinfo=UTC)  # Sun 9:30am ET
REDZONE = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)  # Sun 1:00pm ET
MONDAY = datetime(2026, 9, 22, 0, 15, tzinfo=UTC)  # Mon 8:15pm ET

WINDOWED = WeekSchedule(
    season="2026",
    week=3,
    events=[
        NflEvent("t", "BUF @ MIA", THU, "STATUS_SCHEDULED", ("BUF", "MIA")),
        NflEvent("l", "JAX @ ATL", LONDON, "STATUS_SCHEDULED", ("JAX", "ATL")),
        NflEvent("r", "PHI @ KC", REDZONE, "STATUS_SCHEDULED", ("PHI", "KC")),
        NflEvent("m", "CIN @ CLE", MONDAY, "STATUS_SCHEDULED", ("CIN", "CLE")),
    ],
)


def early(parsed: dict | None, window: datetime | None = REDZONE) -> str | None:
    return leg_rules.too_early(parsed, WINDOWED, window)


def test_a_thursday_player_is_turned_away():
    assert "BUF @ MIA" in early(rushing("James Cook", team="BUF"))


def test_a_thursday_team_bet_is_turned_away_too():
    """The rule is about the game, not about whether a person is named."""
    assert early(team_bet("moneyline", "MIA")) is not None


def test_the_international_morning_game_is_turned_away():
    """Sunday, but three and a half hours before RedZone goes on air."""
    assert "JAX @ ATL" in early(team_bet("moneyline", "JAX"))


def test_a_game_in_the_window_is_fine():
    assert early(rushing("Saquon Barkley")) is None
    assert early(team_bet("moneyline", "KC")) is None


def test_monday_night_is_still_fine():
    """The rule is "not before the window", not "inside the Sunday window"."""
    assert early(team_bet("moneyline", "CIN")) is None


def test_the_refusal_says_what_to_do_instead():
    message = early(team_bet("moneyline", "BUF"))
    assert "before this league's window opens" in message
    assert "starts then or later" in message


def test_a_league_without_a_window_turns_nothing_away():
    assert early(team_bet("moneyline", "BUF"), window=None) is None


def test_a_team_the_schedule_cannot_place_is_left_alone():
    """A bye or a misread abbreviation is not evidence of anything."""
    assert early(team_bet("moneyline", "SEA")) is None


def test_an_unread_leg_is_left_alone():
    assert early(None) is None
    assert early({"understood": False}) is None
