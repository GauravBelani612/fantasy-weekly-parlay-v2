"""Grading a live round end to end: read, grade, settle, announce, correct.

ESPN and the parser are faked; everything between them is real, including the database,
the notification ledger and the settle rules.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.integrations import espn
from app.integrations.espn import GameSummary, NflEvent, PlayerLine, WeekSchedule
from app.models import Leg, NotificationLog, ParlayRound
from app.services import grading, leg_parser, notify, round_grading

APP = "https://app.example"
KICK = datetime(2026, 9, 18, tzinfo=UTC)

# How the fake parser reads each leg -- standing in for Claude.
READINGS = {
    "Chase Brown TD": {"understood": True, "market": "touchdowns", "subject": "Chase Brown",
                       "team": "CIN", "direction": "at_least", "line": 1, "note": ""},
    "Saquon TD": {"understood": True, "market": "touchdowns", "subject": "Saquon Barkley",
                  "team": "PHI", "direction": "at_least", "line": 1, "note": ""},
    "Jordan love over passing yards": {"understood": True, "market": "passing_yards",
                                       "subject": "Jordan Love", "team": "GB",
                                       "direction": "over", "line": None, "note": ""},
}


class FakeEspn:
    """A week of games whose finality and box scores the test controls."""

    def __init__(self):
        self.final: set[str] = set()
        self.players: dict[str, list[PlayerLine]] = {
            "cin": [PlayerLine("Chase Brown", "CIN", {"rushing_touchdowns": 1})],
            "phi": [PlayerLine("Saquon Barkley", "PHI", {"rushing_touchdowns": 0})],
            "gb": [PlayerLine("Jordan Love", "GB", {"passing_yards": 247})],
        }
        self.teams = {"cin": ("CIN", "JAX"), "phi": ("PHI", "KC"), "gb": ("GB", "WSH")}
        self.summary_calls = 0

    async def schedule(self, season: str, week: int) -> WeekSchedule:
        events = [
            NflEvent(eid, " @ ".join(t), KICK,
                     "STATUS_FINAL" if eid in self.final else "STATUS_SCHEDULED", t)
            for eid, t in self.teams.items()
        ]
        return WeekSchedule(season=season, week=week, events=events)

    async def summary(self, event_id: str) -> GameSummary:
        self.summary_calls += 1
        home, away = self.teams[event_id]
        return GameSummary(event_id, "STATUS_FINAL", {home: 24, away: 20},
                           self.players[event_id])


@pytest.fixture
def fake_espn(monkeypatch):
    fake = FakeEspn()
    monkeypatch.setattr(espn, "get_week_schedule", fake.schedule)
    monkeypatch.setattr(espn, "get_game_summary", fake.summary)
    return fake


@pytest.fixture
def parser_calls(monkeypatch):
    calls: list[str] = []

    async def fake_parse(raw_text, matchups=None, week=None, **_):
        calls.append(raw_text)
        return READINGS.get(raw_text)

    monkeypatch.setattr(leg_parser, "parse_leg", fake_parse)
    return calls


@pytest.fixture
def outbox(monkeypatch):
    sent = {"email": [], "webhook": []}

    async def fake_email(to, subject, html):
        sent["email"].append((to, subject, html))
        return True

    async def fake_webhook(url, content):
        sent["webhook"].append(content)
        return True

    monkeypatch.setattr(notify, "send_email", fake_email)
    monkeypatch.setattr(notify, "send_webhook", fake_webhook)
    return sent


@pytest_asyncio.fixture
async def live(session, user_factory, league_factory, member_factory):
    """Week 2: Gaurav pays, three legs in, legs locked, games about to start."""
    league = await league_factory(season="2026")
    league.discord_webhook_url = "https://discord.example/hook"
    session.add(league)

    gaurav = await user_factory("gaurav", sleeper_user_id="S1")
    byju = await user_factory("byju", sleeper_user_id="S2")
    nord = await user_factory("nord", sleeper_user_id="S3")
    g_m = await member_factory(league, 1, "Gaurav612", user=gaurav, role="commissioner")
    b_m = await member_factory(league, 2, "BigBootyByju", user=byju)
    n_m = await member_factory(league, 3, "nordstromracked", user=nord)

    now = datetime.now(UTC)
    rnd = ParlayRound(league_id=league.id, season="2026", scored_week=1, bet_week=2,
                      loser_member_id=g_m.id, loser_points=74.86,
                      opens_at=now - timedelta(days=2), locks_at=now - timedelta(hours=1))
    session.add(rnd)
    await session.flush()
    legs = {
        "brown": Leg(round_id=rnd.id, member_id=b_m.id, raw_text="Chase Brown TD"),
        "saquon": Leg(round_id=rnd.id, member_id=g_m.id, raw_text="Saquon TD"),
        "love": Leg(round_id=rnd.id, member_id=n_m.id, raw_text="Jordan love over passing yards"),
    }
    session.add_all(legs.values())
    await session.commit()
    return {"league": league, "round": rnd, "legs": legs,
            "gaurav": gaurav, "byju": byju, "g_m": g_m, "b_m": b_m}


async def _grade(session, live):
    return await round_grading.grade_round(session, live["league"], live["round"], APP)


async def _refresh(session, *objs):
    for obj in objs:
        await session.refresh(obj)


# ------------------------------------------------------------------ reading and grading


async def test_unread_legs_are_read_once(session, live, fake_espn, parser_calls, outbox):
    await _grade(session, live)
    await _grade(session, live)
    assert sorted(parser_calls) == sorted(READINGS), "each leg read exactly once"


async def test_before_kickoff_the_payer_is_asked_for_the_missing_line(
    session, live, fake_espn, parser_calls, outbox
):
    await _grade(session, live)
    legs = live["legs"]
    await _refresh(session, *legs.values())
    assert legs["love"].result == grading.NEEDS_LINE
    assert legs["brown"].result == grading.PENDING
    assert outbox["email"] == []


async def test_a_finished_game_grades_its_legs(session, live, fake_espn, parser_calls, outbox):
    fake_espn.final.add("cin")
    await _grade(session, live)
    brown = live["legs"]["brown"]
    await _refresh(session, brown)
    assert brown.result == grading.HIT
    assert brown.graded_by == "espn"
    assert brown.grade_detail == "Chase Brown: 1 TD, needed 1+"


# ------------------------------------------------------------------ settling


async def test_one_miss_busts_it_immediately_and_tells_the_whole_league(
    session, live, fake_espn, parser_calls, outbox
):
    fake_espn.final.add("phi")  # Saquon doesn't score; the other games haven't finished
    await _grade(session, live)

    rnd = live["round"]
    await _refresh(session, rnd)
    assert rnd.outcome == "lost"

    recipients = {to for to, _, _ in outbox["email"]}
    assert recipients == {"gaurav@example.com", "byju@example.com", "nord@example.com"}
    subject, html = outbox["email"][0][1], outbox["email"][0][2]
    assert "week 2 parlay busted" in subject
    assert "Saquon TD" in html and "Sunk by" in html
    assert "sunk by Gaurav612's Saquon TD" in outbox["webhook"][0]


async def test_the_bust_is_announced_once(session, live, fake_espn, parser_calls, outbox):
    fake_espn.final.add("phi")
    await _grade(session, live)
    await _grade(session, live)
    assert len(outbox["email"]) == 3
    assert len(outbox["webhook"]) == 1


async def test_every_leg_hitting_cashes_it(session, live, fake_espn, parser_calls, outbox):
    fake_espn.players["phi"] = [PlayerLine("Saquon Barkley", "PHI", {"rushing_touchdowns": 2})]
    live["legs"]["love"].payer_line = 224.5
    await session.commit()
    fake_espn.final.update({"cin", "phi", "gb"})

    await _grade(session, live)
    rnd = live["round"]
    await _refresh(session, rnd)
    assert rnd.outcome == "won"
    assert "parlay cashed" in outbox["email"][0][1]


async def test_the_grader_never_overturns_a_settled_outcome(
    session, live, fake_espn, parser_calls, outbox
):
    rnd = live["round"]
    rnd.outcome = "won"  # e.g. recorded by hand on the History page
    await session.commit()
    fake_espn.final.add("phi")  # a miss

    await _grade(session, live)
    await _refresh(session, rnd)
    assert rnd.outcome == "won"
    assert outbox["email"] == []


async def test_settled_legs_are_not_regraded(session, live, fake_espn, parser_calls, outbox):
    """A stat correction must not flip a result the league was already emailed about."""
    fake_espn.final.add("cin")
    await _grade(session, live)
    fake_espn.players["cin"] = [PlayerLine("Chase Brown", "CIN", {"rushing_touchdowns": 0})]
    calls = fake_espn.summary_calls

    await _grade(session, live)
    brown = live["legs"]["brown"]
    await _refresh(session, brown)
    assert brown.result == grading.HIT
    assert fake_espn.summary_calls == calls, "no box score fetched for a settled leg"


async def test_monday_night_legs_are_graded_after_the_week_moves_on(
    session, live, fake_espn, parser_calls, outbox
):
    """Once the last game ends, the 'current' round is next week's -- grading must not
    depend on which round is current, or Monday night would never be graded."""
    fake_espn.final.update({"cin", "phi", "gb"})
    await round_grading.grade_league(session, live["league"], APP)
    saquon = live["legs"]["saquon"]
    await _refresh(session, saquon)
    assert saquon.result == grading.MISS


async def test_rounds_past_the_grading_window_are_left_alone(
    session, live, fake_espn, parser_calls, outbox
):
    rnd = live["round"]
    rnd.locks_at = datetime.now(UTC) - round_grading.GRADE_WINDOW - timedelta(days=1)
    await session.commit()
    fake_espn.final.update({"cin", "phi", "gb"})

    await round_grading.grade_league(session, live["league"], APP)
    assert parser_calls == []


# ------------------------------------------------------------------ people correcting it


async def test_a_hand_set_result_is_never_touched_by_the_grader(
    session, live, fake_espn, parser_calls, outbox
):
    love = live["legs"]["love"]
    await round_grading.set_leg(session, live["league"], live["round"], love, live["g_m"],
                                {"result": "hit"}, APP)
    fake_espn.final.add("gb")
    await _grade(session, live)

    await _refresh(session, love)
    assert (love.result, love.graded_by) == (grading.HIT, "manual")
    assert love.grade_detail == "Marked hit by Gaurav612"


async def test_recording_a_line_after_the_game_settles_it_on_the_spot(
    session, live, fake_espn, parser_calls, outbox
):
    fake_espn.final.add("gb")
    await _grade(session, live)
    love = live["legs"]["love"]
    await _refresh(session, love)
    assert love.result == grading.NEEDS_LINE

    await round_grading.set_leg(session, live["league"], live["round"], love, live["g_m"],
                                {"line": 224.5}, APP)
    await _refresh(session, love)
    assert love.result == grading.HIT
    assert love.grade_detail == "Jordan Love: 247 passing yds, line over 224.5"


async def test_correcting_a_wrong_bust_reopens_it_and_a_later_cash_is_announced(
    session, live, fake_espn, parser_calls, outbox
):
    """The case that forced two settle rules: a misgraded Thursday leg must not leave the
    parlay stuck at lost once every leg has actually come in."""
    fake_espn.final.add("phi")
    await _grade(session, live)
    rnd = live["round"]
    await _refresh(session, rnd)
    assert rnd.outcome == "lost"
    busted = len(outbox["email"])

    saquon = live["legs"]["saquon"]
    await round_grading.set_leg(session, live["league"], rnd, saquon, live["g_m"],
                                {"result": "hit"}, APP)
    await _refresh(session, rnd)
    assert rnd.outcome == grading.PENDING, "the correction reopens the parlay"

    live["legs"]["love"].payer_line = 224.5
    await session.commit()
    fake_espn.final.update({"cin", "gb"})
    await _grade(session, live)

    await _refresh(session, rnd)
    assert rnd.outcome == "won"
    new_subjects = [subject for _, subject, _ in outbox["email"][busted:]]
    assert new_subjects and all("cashed" in s for s in new_subjects)

    kinds = {k for (k,) in (await session.execute(select(NotificationLog.kind))).all()}
    assert {"resolved_lost", "resolved_won"} <= kinds
