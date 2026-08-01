"""Leg submission rules the Google Form could never enforce."""

from datetime import UTC, datetime, timedelta

import pytest_asyncio

from app.models import ParlayRound


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
