"""Leg grading -- the code a league argues with.

Cases use this league's real week 2 legs wherever they fit, so a failure reads as the
actual bet that would have been settled wrong.
"""

from datetime import UTC, datetime

import pytest

from app.integrations.espn import GameSummary, NflEvent, PlayerLine, WeekSchedule
from app.services import grading as g

KICK = datetime(2026, 9, 18, tzinfo=UTC)


def player(name: str, team: str, **stats: float) -> PlayerLine:
    return PlayerLine(name=name, team=team, stats=stats)


def event(event_id: str, *teams: str, final: bool = True) -> NflEvent:
    return NflEvent(
        event_id=event_id,
        name=" @ ".join(teams),
        kickoff_at=KICK,
        status="STATUS_FINAL" if final else "STATUS_IN_PROGRESS",
        teams=teams,
    )


def game(event_id, scores, players=(), ruled_out=None, final=True) -> GameSummary:
    return GameSummary(
        event_id=event_id,
        status="STATUS_FINAL" if final else "STATUS_IN_PROGRESS",
        scores=scores,
        players=list(players),
        ruled_out=ruled_out or {},
    )


def week(*events: NflEvent) -> WeekSchedule:
    return WeekSchedule(season="2026", week=2, events=list(events))


def loader(*summaries: GameSummary):
    by_id = {s.event_id: s for s in summaries}

    async def load(event_id: str):
        return by_id.get(event_id)

    return load


def leg(**fields) -> dict:
    return {"understood": True, **fields}


def anytime_td(name: str, team: str | None) -> dict:
    return leg(market="touchdowns", subject=name, team=team, direction="at_least", line=1)


# ------------------------------------------------------------- the league's real legs


async def test_chase_brown_td_hits_on_a_rushing_touchdown():
    sched = week(event("1", "CIN", "JAX"))
    box = game("1", {"CIN": 24, "JAX": 20}, [player("Chase Brown", "CIN", rushing_touchdowns=1)])
    grade = await g.grade_leg(anytime_td("Chase Brown", "CIN"), None, sched, loader(box))
    assert grade.result == g.HIT
    assert grade.detail == "Chase Brown: 1 TD, needed 1+"


async def test_bijan_two_tds_sums_rushing_and_receiving():
    """Neither category alone reaches two -- only the sum does."""
    sched = week(event("1", "ATL", "MIN"))
    box = game(
        "1",
        {"ATL": 30, "MIN": 17},
        [player("Bijan Robinson", "ATL", rushing_touchdowns=1, receiving_touchdowns=1)],
    )
    parsed = leg(market="touchdowns", subject="Bijan Robinson", team="ATL",
                 direction="at_least", line=2)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == g.HIT


async def test_mcbride_three_plus_receptions_is_inclusive():
    sched = week(event("1", "ARI", "SEA"))
    box = game("1", {"ARI": 20, "SEA": 23}, [player("Trey McBride", "ARI", receptions=3)])
    parsed = leg(market="receptions", subject="Trey McBride", team="ARI",
                 direction="at_least", line=3)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == g.HIT


async def test_jordan_love_over_passing_yards_needs_a_line_before_kickoff():
    """Asked for up front, so the payer can record it when placing the bet."""
    sched = week(event("1", "GB", "WSH", final=False))
    parsed = leg(market="passing_yards", subject="Jordan Love", team="GB",
                 direction="over", line=None)
    grade = await g.grade_leg(parsed, None, sched, loader())
    assert grade.result == g.NEEDS_LINE


async def test_a_recorded_line_settles_the_same_leg():
    sched = week(event("1", "GB", "WSH"))
    box = game("1", {"GB": 27, "WSH": 21}, [player("Jordan Love", "GB", passing_yards=247)])
    parsed = leg(market="passing_yards", subject="Jordan Love", team="GB",
                 direction="over", line=None)
    grade = await g.grade_leg(parsed, 224.5, sched, loader(box))
    assert grade.result == g.HIT
    assert grade.detail == "Jordan Love: 247 passing yds, line over 224.5"


async def test_the_recorded_line_beats_one_in_the_text():
    """The payer's number is what was actually placed."""
    sched = week(event("1", "GB", "WSH"))
    box = game("1", {"GB": 27, "WSH": 21}, [player("Jordan Love", "GB", passing_yards=240)])
    parsed = leg(market="passing_yards", subject="Jordan Love", team="GB",
                 direction="over", line=224.5)
    assert (await g.grade_leg(parsed, 249.5, sched, loader(box))).result == g.MISS


async def test_giants_moneyline():
    sched = week(event("1", "NYG", "DAL"))
    parsed = leg(market="moneyline", team="NYG")
    won = await g.grade_leg(parsed, None, sched, loader(game("1", {"NYG": 24, "DAL": 20})))
    lost = await g.grade_leg(parsed, None, sched, loader(game("1", {"NYG": 17, "DAL": 20})))
    assert (won.result, lost.result) == (g.HIT, g.MISS)
    assert won.detail == "NYG 24, DAL 20"


async def test_a_misspelled_name_still_matches():
    """'Chubba hubbard' as typed by a league member."""
    sched = week(event("1", "CAR", "NO"))
    box = game("1", {"CAR": 13, "NO": 16}, [player("Chuba Hubbard", "CAR", rushing_yards=81)])
    parsed = leg(market="rushing_yards", subject="Chubba Hubbard", team="CAR",
                 direction="over", line=70.5)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == g.HIT


# ------------------------------------------------------------- settlement rules


@pytest.mark.parametrize(
    ("yards", "expected"),
    [(71, g.HIT), (70, g.MISS), (69, g.MISS)],
)
async def test_landing_exactly_on_an_over_line_is_a_miss(yards, expected):
    """No pushes, by league rule: exactly 70 did not go over 70."""
    sched = week(event("1", "CAR", "NO"))
    box = game("1", {"CAR": 13, "NO": 16}, [player("Chuba Hubbard", "CAR", rushing_yards=yards)])
    parsed = leg(market="rushing_yards", subject="Chuba Hubbard", team="CAR",
                 direction="over", line=70)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == expected


async def test_under():
    sched = week(event("1", "CAR", "NO"))
    box = game("1", {"CAR": 13, "NO": 16}, [player("Chuba Hubbard", "CAR", rushing_yards=40)])
    parsed = leg(market="rushing_yards", subject="Chuba Hubbard", team="CAR",
                 direction="under", line=55.5)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == g.HIT


async def test_a_quarterbacks_passing_touchdowns_are_not_anytime_touchdowns():
    sched = week(event("1", "CIN", "TB"))
    box = game("1", {"CIN": 33, "TB": 27},
               [player("Joe Burrow", "CIN", passing_touchdowns=3, rushing_touchdowns=0)])
    grade = await g.grade_leg(anytime_td("Joe Burrow", "CIN"), None, sched, loader(box))
    assert grade.result == g.MISS


async def test_a_return_touchdown_is_an_anytime_touchdown():
    sched = week(event("1", "CIN", "TB"))
    box = game("1", {"CIN": 33, "TB": 27}, [player("Chase Brown", "CIN", return_touchdowns=1)])
    grade = await g.grade_leg(anytime_td("Chase Brown", "CIN"), None, sched, loader(box))
    assert grade.result == g.HIT


@pytest.mark.parametrize(
    ("bills", "jets", "line", "expected"),
    [
        (27, 23, -3.5, g.HIT),
        (26, 23, -3.5, g.MISS),
        (26, 23, -3.0, g.MISS),  # covering by exactly the number is not covering
        (20, 23, +3.5, g.HIT),
    ],
)
async def test_spread(bills, jets, line, expected):
    sched = week(event("1", "BUF", "NYJ"))
    parsed = leg(market="spread", team="BUF", line=line)
    box = game("1", {"BUF": bills, "NYJ": jets})
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == expected


@pytest.mark.parametrize("points", [23, 20])
async def test_landing_exactly_on_an_under_line_is_a_miss(points):
    sched = week(event("1", "CAR", "NO"))
    box = game("1", {"CAR": 13, "NO": 16}, [player("Chuba Hubbard", "CAR", rushing_yards=points)])
    parsed = leg(market="rushing_yards", subject="Chuba Hubbard", team="CAR",
                 direction="under", line=20)
    assert (await g.grade_leg(parsed, None, sched, loader(box))).result == g.MISS


async def test_a_tied_moneyline_is_a_miss():
    sched = week(event("1", "NYG", "DAL"))
    parsed = leg(market="moneyline", team="NYG")
    grade = await g.grade_leg(parsed, None, sched, loader(game("1", {"NYG": 20, "DAL": 20})))
    assert grade.result == g.MISS


async def test_no_result_is_ever_a_push():
    """Guards the league rule itself, not just the cases above."""
    assert not hasattr(g, "PUSH")
    assert "push" not in g.TERMINAL
    assert "push" not in g.MANUAL_RESULTS


async def test_game_total():
    sched = week(event("1", "KC", "PHI"))
    parsed = leg(market="game_total", team="KC", direction="over", line=47.5)
    grade = await g.grade_leg(parsed, None, sched, loader(game("1", {"KC": 27, "PHI": 24})))
    assert grade.result == g.HIT
    assert "total 51" in grade.detail


# ------------------------------------------------------------- when it can't settle


async def test_waits_for_the_game_to_finish_and_says_when_it_starts():
    sched = week(event("1", "PHI", "KC", final=False))
    grade = await g.grade_leg(
        anytime_td("Saquon Barkley", "PHI"), None, sched, loader(), "America/New_York"
    )
    assert grade.result == g.PENDING
    # KICK is 2026-09-18 00:00 UTC -- Thursday evening in New York.
    assert grade.detail == "Waiting on PHI @ KC · Thu 8 PM EDT"


@pytest.mark.parametrize(
    ("kickoff", "timezone", "expected"),
    [
        # Sunday 1pm ET, the most common slot: no ":00" on the hour.
        (datetime(2026, 9, 20, 17, 0, tzinfo=UTC), "America/New_York", "Sun 1 PM EDT"),
        (datetime(2026, 9, 21, 0, 20, tzinfo=UTC), "America/New_York", "Sun 8:20 PM EDT"),
        # The same kickoff, read from a league set to the west coast.
        (datetime(2026, 9, 20, 17, 0, tzinfo=UTC), "America/Los_Angeles", "Sun 10 AM PDT"),
        # December: the clocks have gone back.
        (datetime(2026, 12, 20, 18, 0, tzinfo=UTC), "America/New_York", "Sun 1 PM EST"),
        # An unusable timezone falls back rather than raising mid-grade.
        (datetime(2026, 9, 20, 17, 0, tzinfo=UTC), "Not/AZone", "Sun 5 PM UTC"),
    ],
)
def test_kickoff_text(kickoff, timezone, expected):
    kicking = NflEvent("1", "CIN @ HOU", kickoff, "STATUS_SCHEDULED", ("CIN", "HOU"))
    assert g.kickoff_text(kicking, timezone) == expected


async def test_a_ruled_out_player_voids_the_leg():
    sched = week(event("1", "NYG", "DAL"))
    box = game("1", {"NYG": 24, "DAL": 20}, [], ruled_out={"Malik Nabers": "Injured Reserve"})
    grade = await g.grade_leg(anytime_td("Malik Nabers", "NYG"), None, sched, loader(box))
    assert grade.result == g.VOID
    assert "Injured Reserve" in grade.detail


async def test_a_player_simply_missing_from_the_box_score_is_left_for_a_person():
    """Could be inactive, could be a misread name -- voiding would guess."""
    sched = week(event("1", "NYG", "DAL"))
    box = game("1", {"NYG": 24, "DAL": 20}, [player("Someone Else", "NYG", receptions=4)])
    grade = await g.grade_leg(anytime_td("Malik Nabers", "NYG"), None, sched, loader(box))
    assert grade.result == g.UNRESOLVED


async def test_a_team_not_playing_this_week_is_unresolved():
    sched = week(event("1", "NYG", "DAL"))
    parsed = leg(market="moneyline", team="SEA")
    grade = await g.grade_leg(parsed, None, sched, loader(game("1", {"NYG": 1, "DAL": 0})))
    assert grade.result == g.UNRESOLVED
    assert "SEA don't play in week 2" in grade.detail


async def test_an_unread_leg_waits_and_an_unreadable_one_says_why():
    sched = week(event("1", "NYG", "DAL"))
    assert (await g.grade_leg(None, None, sched, loader())).result == g.PENDING
    bad = {"understood": False, "note": "Not a bet"}
    grade = await g.grade_leg(bad, None, sched, loader())
    assert (grade.result, grade.detail) == (g.UNRESOLVED, "Not a bet")


# ------------------------------------------------------------- same-name players


async def test_the_named_team_is_the_only_game_searched():
    """Josh Allen the Jaguars linebacker must never grade Josh Allen the Bills QB."""
    sched = week(event("1", "BUF", "MIA"), event("2", "JAX", "HOU"))
    buf = game("1", {"BUF": 31, "MIA": 10}, [player("Josh Allen", "BUF", passing_touchdowns=3)])
    jax = game("2", {"JAX": 20, "HOU": 17}, [player("Josh Allen", "JAX", passing_touchdowns=0)])
    parsed = leg(market="passing_touchdowns", subject="Josh Allen", team="BUF",
                 direction="at_least", line=2)
    assert (await g.grade_leg(parsed, None, sched, loader(buf, jax))).result == g.HIT


async def test_a_ruled_out_namesake_cannot_void_a_player_who_played():
    """No team given: the IR linebacker must not void the quarterback's bet."""
    sched = week(event("1", "BUF", "MIA"), event("2", "JAX", "HOU"))
    buf = game("1", {"BUF": 31, "MIA": 10}, [player("Josh Allen", "BUF", passing_touchdowns=3)])
    jax = game("2", {"JAX": 20, "HOU": 17}, [], ruled_out={"Josh Allen": "Injured Reserve"})
    parsed = leg(market="passing_touchdowns", subject="Josh Allen", team=None,
                 direction="at_least", line=2)
    assert (await g.grade_leg(parsed, None, sched, loader(jax, buf))).result == g.HIT


async def test_two_players_who_both_played_is_never_guessed():
    sched = week(event("1", "BUF", "MIA"), event("2", "JAX", "HOU"))
    buf = game("1", {"BUF": 31, "MIA": 10}, [player("Josh Allen", "BUF", rushing_touchdowns=1)])
    jax = game("2", {"JAX": 20, "HOU": 17}, [player("Josh Allen", "JAX", return_touchdowns=0)])
    grade = await g.grade_leg(anytime_td("Josh Allen", None), None, sched, loader(buf, jax))
    assert grade.result == g.UNRESOLVED


# ------------------------------------------------------------- the parlay


@pytest.mark.parametrize(
    ("results", "outcome"),
    [
        ([g.HIT, g.MISS, g.PENDING], "lost"),  # one miss ends it, games still to play
        ([g.HIT, g.PENDING], g.PENDING),
        ([g.HIT, g.NEEDS_LINE], g.PENDING),
        ([g.HIT, g.VOID], "won"),  # an inactive player's leg drops out
        ([g.VOID, g.VOID], "void"),
        ([], g.PENDING),
    ],
)
def test_parlay_settles_like_a_sportsbook(results, outcome):
    assert g.resolve_outcome(results) == outcome


# ------------------------------------------------------------- presentation


def test_read_as():
    assert g.read_as(anytime_td("Chase Brown", "CIN")) == "Chase Brown (CIN) · anytime TD"
    assert g.read_as(leg(market="moneyline", team="NYG")) == "NYG · moneyline"
    love = leg(market="passing_yards", subject="Jordan Love", team="GB",
               direction="over", line=None)
    assert g.read_as(love) == "Jordan Love (GB) · passing yds over —"
    assert g.read_as(love, payer_line=224.5) == "Jordan Love (GB) · passing yds over 224.5"
    assert g.read_as({"understood": False}) == "Couldn't read this leg"


@pytest.mark.parametrize(
    ("typed", "espn"),
    [
        ("jamarr chase", "Ja'Marr Chase"),
        ("Brian Parker", "Brian Parker II"),
        ("Amon Ra St Brown", "Amon-Ra St. Brown"),
        ("AMON-RA ST. BROWN", "Amon-Ra St. Brown"),
    ],
)
def test_name_key_lines_up_the_ways_people_type_names(typed, espn):
    assert g.name_key(typed) == g.name_key(espn)
