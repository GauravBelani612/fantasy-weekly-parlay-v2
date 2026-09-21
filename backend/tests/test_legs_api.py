"""Leg submission rules the Google Form could never enforce."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.config import settings
from app.integrations import espn
from app.integrations.espn import NflEvent, WeekSchedule
from app.models import ParlayRound
from app.services import leg_parser

KICK = datetime(2026, 9, 20, 17, 0, tzinfo=UTC)  # Sun 1:00pm ET -- RedZone
THURSDAY = datetime(2026, 9, 18, 0, 15, tzinfo=UTC)  # Thu 8:15pm ET
REDZONE = KICK

SAQUON_OVER = {"understood": True, "market": "rushing_yards", "subject": "Saquon Barkley",
               "team": "PHI", "direction": "over", "line": 50.5, "note": ""}
SAQUON_UNDER = {**SAQUON_OVER, "direction": "under"}
SAQUON_TD = {"understood": True, "market": "touchdowns", "subject": "Saquon Barkley",
             "team": "PHI", "direction": "at_least", "line": 1, "note": ""}


@pytest.fixture
def reader(monkeypatch):
    """Turn on reading-before-accepting, with ESPN and the model both faked.

    Every other test in this file wants the default: no key, so legs are taken unread and
    nothing reaches the network. The conflict rule needs readings to compare, so it asks
    for them here and says what each leg comes back as.
    """
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    async def schedule(season, week):
        events = [
            NflEvent("1", "PHI @ KC", KICK, "STATUS_SCHEDULED", ("PHI", "KC")),
            NflEvent("2", "BUF @ MIA", THURSDAY, "STATUS_SCHEDULED", ("BUF", "MIA")),
        ]
        return WeekSchedule(season=season, week=week, events=events)

    readings: dict[str, dict] = {}

    async def parse(raw_text, matchups=None, week=None, **_):
        return readings.get(raw_text)

    monkeypatch.setattr(espn, "get_week_schedule", schedule)
    monkeypatch.setattr(leg_parser, "parse_leg", parse)
    return readings


@pytest_asyncio.fixture
async def scenario(session, user_factory, league_factory, member_factory):
    """A 3-roster league where Alice and Bob use the app and Carol does not."""
    league = await league_factory()
    alice = await user_factory("alice", sleeper_user_id="S1")
    bob = await user_factory("bob", sleeper_user_id="S2")

    alice_m = await member_factory(league, 1, "Alice", user=alice, role="commissioner")
    bob_m = await member_factory(league, 2, "Bob", user=bob)
    carol_m = await member_factory(league, 3, "Carol")  # never signed up

    now = datetime.now(UTC)
    rnd = ParlayRound(
        league_id=league.id,
        season=league.season,
        scored_week=5,
        bet_week=6,
        loser_member_id=carol_m.id,
        loser_points=71.2,
        opens_at=now - timedelta(days=1),
        locks_at=now + timedelta(days=1),
    )
    session.add(rnd)
    await session.flush()
    await session.commit()

    return {
        "league": league,
        "round": rnd,
        "alice": alice,
        "bob": bob,
        "alice_m": alice_m,
        "bob_m": bob_m,
        "carol_m": carol_m,
    }


async def test_submit_and_everyone_sees_it_live(client, login, scenario):
    rnd = scenario["round"]

    login(scenario["alice"])
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Ja'Marr Chase over 89.5 rec yds"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submitted_count"] == 1
    assert body["eligible_count"] == 2, "Carol has no app account, so she is not eligible"
    assert body["your_leg"]["raw_text"] == "Ja'Marr Chase over 89.5 rec yds"
    assert [m["display_name"] for m in body["awaiting"]] == ["Bob"]

    # Bob sees Alice's leg immediately -- legs are public as they land.
    login(scenario["bob"])
    r = await client.get(f"/rounds/{rnd.id}/legs")
    assert r.status_code == 200
    texts = [leg["raw_text"] for leg in r.json()]
    assert texts == ["Ja'Marr Chase over 89.5 rec yds"]
    assert r.json()[0]["is_you"] is False


async def test_second_submit_replaces_rather_than_duplicates(client, login, scenario):
    rnd = scenario["round"]
    login(scenario["alice"])

    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "KC moneyline"})
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "KC -3.5"})

    assert r.status_code == 200
    body = r.json()
    assert body["submitted_count"] == 1, "one leg per person, always"
    assert body["your_leg"]["raw_text"] == "KC -3.5"


async def test_cannot_submit_after_lock(client, login, scenario, session):
    rnd = scenario["round"]
    rnd.locks_at = datetime.now(UTC) - timedelta(minutes=1)
    session.add(rnd)
    await session.commit()

    login(scenario["alice"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "too late"})
    assert r.status_code == 409
    assert "locked" in r.json()["detail"].lower()


async def test_cannot_submit_before_open(client, login, scenario, session):
    rnd = scenario["round"]
    rnd.opens_at = datetime.now(UTC) + timedelta(hours=2)
    session.add(rnd)
    await session.commit()

    login(scenario["alice"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "too early"})
    assert r.status_code == 409


async def test_non_member_cannot_see_or_touch_the_round(client, login, scenario, user_factory):
    outsider = await user_factory("mallory", sleeper_user_id="S99")
    login(outsider)

    rnd = scenario["round"]
    # 404 rather than 403 so league IDs cannot be probed.
    assert (await client.get(f"/rounds/{rnd.id}")).status_code == 404
    assert (
        await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "nope"})
    ).status_code == 404


async def test_empty_leg_is_rejected(client, login, scenario):
    login(scenario["alice"])
    r = await client.put(f"/rounds/{scenario['round'].id}/legs/me", json={"raw_text": "  "})
    assert r.status_code == 422


async def test_delete_removes_your_leg(client, login, scenario):
    rnd = scenario["round"]
    login(scenario["alice"])
    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Bills -3.5"})

    r = await client.delete(f"/rounds/{rnd.id}/legs/me")
    assert r.status_code == 200
    assert r.json()["submitted_count"] == 0
    assert r.json()["your_leg"] is None

    assert (await client.delete(f"/rounds/{rnd.id}/legs/me")).status_code == 404


async def test_round_flags_a_loser_with_no_app_account(client, login, scenario):
    """Carol lost but never signed up -- the round must still work and say so."""
    login(scenario["alice"])
    r = await client.get(f"/rounds/{scenario['round'].id}")
    body = r.json()
    assert body["loser"]["display_name"] == "Carol"
    assert body["loser_has_app_account"] is False
    assert body["loser"]["has_app_account"] is False


async def test_editing_a_leg_resets_its_grade(client, login, scenario, session):
    from sqlalchemy import select

    from app.models import Leg

    rnd = scenario["round"]
    login(scenario["alice"])
    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Hurts over 1.5 pass TD"})

    leg = await session.scalar(select(Leg).where(Leg.round_id == rnd.id))
    leg.result = "hit"
    leg.parsed = {"player": "Jalen Hurts"}
    session.add(leg)
    await session.commit()

    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Hurts over 2.5 pass TD"})
    await session.refresh(leg)
    assert leg.result == "pending"
    assert leg.parsed is None


async def test_only_commissioner_can_resolve_a_tie(client, login, scenario):
    rnd = scenario["round"]

    login(scenario["bob"])  # plain member
    r = await client.post(
        f"/rounds/{rnd.id}/loser", json={"member_id": str(scenario["bob_m"].id)}
    )
    assert r.status_code == 403

    login(scenario["alice"])  # commissioner
    r = await client.post(
        f"/rounds/{rnd.id}/loser", json={"member_id": str(scenario["bob_m"].id)}
    )
    assert r.status_code == 200
    assert r.json()["loser"]["display_name"] == "Bob"
    assert r.json()["tie_roster_ids"] is None


async def test_only_loser_or_commissioner_records_the_result(client, login, scenario):
    rnd = scenario["round"]

    login(scenario["bob"])  # not the loser, not commissioner
    r = await client.patch(
        f"/rounds/{rnd.id}/result", json={"outcome": "won", "payout_cents": 50000}
    )
    assert r.status_code == 403

    login(scenario["alice"])  # commissioner
    r = await client.patch(
        f"/rounds/{rnd.id}/result",
        json={"outcome": "won", "final_odds": "+1250", "stake_cents": 2000, "payout_cents": 27000},
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "won"
    assert r.json()["final_odds"] == "+1250"


# ------------------------------------------------------------------ one opinion per slip


async def test_a_leg_that_repeats_someone_elses_is_refused(client, login, scenario, reader):
    rnd = scenario["round"]
    reader["Saquon over 50 rush yds"] = SAQUON_OVER
    reader["Saquon under 50 rush yds"] = SAQUON_UNDER

    login(scenario["alice"])
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"}
    )
    assert r.status_code == 200, r.text

    login(scenario["bob"])
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon under 50 rush yds"}
    )
    assert r.status_code == 409, r.text
    assert 'Alice already has "Saquon over 50 rush yds"' in r.json()["detail"]

    # Refused means not stored, not stored-and-flagged.
    r = await client.get(f"/rounds/{rnd.id}/legs")
    assert [leg["raw_text"] for leg in r.json()] == ["Saquon over 50 rush yds"]


async def test_a_different_stat_for_the_same_player_is_taken(client, login, scenario, reader):
    rnd = scenario["round"]
    reader["Saquon over 50 rush yds"] = SAQUON_OVER
    reader["Saquon anytime TD"] = SAQUON_TD

    login(scenario["alice"])
    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"})

    login(scenario["bob"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon anytime TD"})
    assert r.status_code == 200, r.text
    assert r.json()["submitted_count"] == 2


async def test_replacing_your_own_leg_never_clashes_with_it(client, login, scenario, reader):
    """One leg each, so a resubmit is an edit rather than a second bet."""
    rnd = scenario["round"]
    reader["Saquon over 50 rush yds"] = SAQUON_OVER
    reader["Saquon under 50 rush yds"] = SAQUON_UNDER

    login(scenario["alice"])
    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"})
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon under 50 rush yds"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["your_leg"]["raw_text"] == "Saquon under 50 rush yds"


async def test_a_leg_the_parser_could_not_read_is_still_taken(client, login, scenario, reader):
    """An upstream outage must not start turning submissions away."""
    rnd = scenario["round"]
    reader["Saquon over 50 rush yds"] = SAQUON_OVER

    login(scenario["alice"])
    await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"})

    login(scenario["bob"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "whatever bruv"})
    assert r.status_code == 200, r.text
    assert r.json()["submitted_count"] == 2


async def test_the_reading_taken_at_submission_is_kept(client, login, scenario, reader):
    """Read once on the way in, not again in the background."""
    rnd = scenario["round"]
    reader["Saquon over 50 rush yds"] = SAQUON_OVER

    login(scenario["alice"])
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["your_leg"]["read_as"] == "Saquon Barkley (PHI) · rushing yds over 50.5"


# ------------------------------------------------------------------ betting from RedZone on


async def test_a_game_before_the_window_is_refused(client, login, scenario, reader, session):
    """A RedZone league will not take a Thursday leg, however well formed it is."""
    rnd = scenario["round"]
    rnd.window_opens_at = REDZONE
    session.add(rnd)
    await session.commit()

    reader["Josh Allen anytime TD"] = {
        "understood": True, "market": "touchdowns", "subject": "Josh Allen",
        "team": "BUF", "direction": "at_least", "line": 1, "note": "",
    }

    login(scenario["alice"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Josh Allen anytime TD"})
    assert r.status_code == 409, r.text
    assert "BUF @ MIA" in r.json()["detail"]
    assert "Sunday RedZone" in r.json()["detail"]

    r = await client.get(f"/rounds/{rnd.id}/legs")
    assert r.json() == []


async def test_a_game_inside_the_window_is_taken(client, login, scenario, reader, session):
    rnd = scenario["round"]
    rnd.window_opens_at = REDZONE
    session.add(rnd)
    await session.commit()

    reader["Saquon over 50 rush yds"] = SAQUON_OVER

    login(scenario["alice"])
    r = await client.put(
        f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Saquon over 50 rush yds"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["window_opens_at"] is not None


async def test_without_a_window_a_thursday_leg_is_fine(client, login, scenario, reader):
    """The default league bets the whole week, Thursday included."""
    rnd = scenario["round"]
    reader["Josh Allen anytime TD"] = {
        "understood": True, "market": "touchdowns", "subject": "Josh Allen",
        "team": "BUF", "direction": "at_least", "line": 1, "note": "",
    }

    login(scenario["alice"])
    r = await client.put(f"/rounds/{rnd.id}/legs/me", json={"raw_text": "Josh Allen anytime TD"})
    assert r.status_code == 200, r.text
