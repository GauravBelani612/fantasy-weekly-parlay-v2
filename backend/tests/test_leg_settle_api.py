"""PATCH /rounds/{id}/legs/{leg_id}: the payer recording a line, or tapping hit or miss."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.integrations import espn
from app.integrations.espn import WeekSchedule
from app.models import Leg, ParlayRound
from app.services import leg_parser

LOVE = {"understood": True, "market": "passing_yards", "subject": "Jordan Love", "team": "GB",
        "direction": "over", "line": None, "note": ""}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No network: an empty week, and a parser that reads nothing new."""

    async def schedule(season, week):
        return WeekSchedule(season=season, week=week, events=[])

    async def parse(*_, **__):
        return None

    monkeypatch.setattr(espn, "get_week_schedule", schedule)
    monkeypatch.setattr(leg_parser, "parse_leg", parse)


@pytest_asyncio.fixture
async def board(session, user_factory, league_factory, member_factory):
    """Alice commissions, Bob pays, Dan is just playing. Dan's leg has no line."""
    league = await league_factory(season="2026")
    alice = await user_factory("alice", sleeper_user_id="S1")
    bob = await user_factory("bob", sleeper_user_id="S2")
    dan = await user_factory("dan", sleeper_user_id="S3")
    alice_m = await member_factory(league, 1, "Alice", user=alice, role="commissioner")
    bob_m = await member_factory(league, 2, "Bob", user=bob)
    dan_m = await member_factory(league, 3, "Dan", user=dan)

    now = datetime.now(UTC)
    rnd = ParlayRound(league_id=league.id, season="2026", scored_week=1, bet_week=2,
                      loser_member_id=bob_m.id, loser_points=70.0,
                      opens_at=now - timedelta(days=1), locks_at=now + timedelta(days=1))
    session.add(rnd)
    await session.flush()
    leg = Leg(round_id=rnd.id, member_id=dan_m.id,
              raw_text="Jordan love over passing yards", parsed=LOVE)
    session.add(leg)
    await session.commit()
    return {"round": rnd, "leg": leg, "alice": alice, "bob": bob, "dan": dan,
            "alice_m": alice_m}


def _url(board) -> str:
    return f"/rounds/{board['round'].id}/legs/{board['leg'].id}"


def _leg(body: dict, leg_id) -> dict:
    return next(x for x in body["legs"] if x["id"] == str(leg_id))


async def test_the_board_shows_how_a_leg_was_read_and_that_it_needs_a_line(
    client, login, board
):
    login(board["dan"])
    body = (await client.get(f"/rounds/{board['round'].id}")).json()
    leg = _leg(body, board["leg"].id)
    assert leg["read_as"] == "Jordan Love (GB) · passing yds over —"
    assert leg["needs_line"] is True


async def test_the_payer_records_the_line(client, login, board):
    login(board["bob"])
    r = await client.patch(_url(board), json={"line": 224.5})
    assert r.status_code == 200, r.text
    leg = _leg(r.json(), board["leg"].id)
    assert leg["payer_line"] == 224.5
    assert leg["needs_line"] is False
    assert leg["read_as"] == "Jordan Love (GB) · passing yds over 224.5"


async def test_the_payer_can_just_tap_hit(client, login, board):
    login(board["bob"])
    r = await client.patch(_url(board), json={"result": "hit"})
    assert r.status_code == 200, r.text
    leg = _leg(r.json(), board["leg"].id)
    assert (leg["result"], leg["graded_by"]) == ("hit", "manual")
    assert leg["grade_detail"] == "Marked hit by Bob"
    assert leg["needs_line"] is False, "settled by hand, so no line is needed"


async def test_the_commissioner_can_settle_a_leg(client, login, board):
    login(board["alice"])
    r = await client.patch(_url(board), json={"result": "miss"})
    assert r.status_code == 200, r.text
    assert _leg(r.json(), board["leg"].id)["result"] == "miss"


async def test_anyone_else_is_refused(client, login, board):
    login(board["dan"])  # his own leg, but he is neither payer nor commissioner
    r = await client.patch(_url(board), json={"result": "hit"})
    assert r.status_code == 403


async def test_pending_hands_the_leg_back_to_the_grader(client, login, board):
    login(board["bob"])
    await client.patch(_url(board), json={"result": "hit"})
    r = await client.patch(_url(board), json={"result": "pending"})
    leg = _leg(r.json(), board["leg"].id)
    assert leg["graded_by"] is None
    assert leg["needs_line"] is True


async def test_a_null_line_clears_it_but_omitting_it_does_not(client, login, board):
    login(board["bob"])
    await client.patch(_url(board), json={"line": 224.5})

    kept = await client.patch(_url(board), json={"result": "pending"})
    assert _leg(kept.json(), board["leg"].id)["payer_line"] == 224.5

    cleared = await client.patch(_url(board), json={"line": None})
    assert _leg(cleared.json(), board["leg"].id)["payer_line"] is None


@pytest.mark.parametrize(
    "payload", [{}, {"result": "won"}, {"result": "HIT"}, {"result": "push"}]
)
async def test_bad_requests_are_rejected(client, login, board, payload):
    login(board["bob"])
    r = await client.patch(_url(board), json=payload)
    assert r.status_code == 422


async def test_a_leg_from_another_round_is_not_found(client, login, board, session):
    other = ParlayRound(league_id=board["round"].league_id, season="2026", scored_week=2,
                        bet_week=3, opens_at=datetime.now(UTC), locks_at=datetime.now(UTC))
    session.add(other)
    await session.commit()

    login(board["bob"])
    r = await client.patch(f"/rounds/{other.id}/legs/{board['leg'].id}", json={"result": "hit"})
    assert r.status_code in (403, 404)  # Bob doesn't pay that round either way


async def test_editing_the_leg_text_discards_the_old_line_and_reading(client, login, board):
    """A recorded line belonged to the old bet."""
    login(board["bob"])
    await client.patch(_url(board), json={"line": 224.5})

    login(board["dan"])
    r = await client.put(f"/rounds/{board['round'].id}/legs/me",
                         json={"raw_text": "Jordan Love 2+ passing TDs"})
    assert r.status_code == 200, r.text
    leg = r.json()["your_leg"]
    assert leg["payer_line"] is None
    assert leg["read_as"] is None, "the old reading is gone until the new text is read"


async def test_resubmitting_identical_text_keeps_the_line(client, login, board):
    login(board["bob"])
    await client.patch(_url(board), json={"line": 224.5})

    login(board["dan"])
    r = await client.put(f"/rounds/{board['round'].id}/legs/me",
                         json={"raw_text": "Jordan love over passing yards"})
    assert r.json()["your_leg"]["payer_line"] == 224.5
