"""Deleting a league removes it and everything hanging off it.

The cascade is worth testing rather than trusting: the foreign keys declare
ON DELETE CASCADE, but SQLite ignores foreign keys unless PRAGMA foreign_keys is
enabled, and these tests run on SQLite. If the service ever stops deleting children
by hand, these assertions fail here instead of leaving orphans in production.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import League, LeagueMember, Leg, ParlayRound, WeekScore


async def _count(session, model, **where) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in where.items():
        stmt = stmt.where(getattr(model, col) == val)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_commissioner_deletes_league_and_its_rows(
    client, session, login, user_factory, league_factory, member_factory
):
    boss = await user_factory("boss", sleeper_user_id="S1")
    league = await league_factory("Doomed")
    commissioner = await member_factory(league, 1, "Boss", user=boss, role="commissioner")
    await member_factory(league, 2, "Unclaimed Roster")

    rnd = ParlayRound(
        league_id=league.id,
        season=league.season,
        scored_week=1,
        bet_week=2,
        opens_at=datetime.now(UTC) - timedelta(hours=1),
        locks_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(rnd)
    await session.flush()
    session.add(Leg(round_id=rnd.id, member_id=commissioner.id, raw_text="Bills -3.5"))
    session.add(
        WeekScore(
            league_id=league.id, season=league.season, week=1, sleeper_roster_id=1, points=88.4
        )
    )
    await session.commit()

    login(boss)
    response = await client.delete(f"/leagues/{league.id}")
    assert response.status_code == 204

    assert await _count(session, League, id=league.id) == 0
    assert await _count(session, LeagueMember, league_id=league.id) == 0
    assert await _count(session, ParlayRound, league_id=league.id) == 0
    assert await _count(session, WeekScore, league_id=league.id) == 0
    # The leg hung off the round, not the league, so it is the easiest one to orphan.
    assert await _count(session, Leg, round_id=rnd.id) == 0


@pytest.mark.asyncio
async def test_ordinary_member_cannot_delete(
    client, session, login, user_factory, league_factory, member_factory
):
    boss = await user_factory("boss2", sleeper_user_id="S10")
    player = await user_factory("player", sleeper_user_id="S11")
    league = await league_factory("Survives")
    await member_factory(league, 1, "Boss", user=boss, role="commissioner")
    await member_factory(league, 2, "Player", user=player)

    login(player)
    response = await client.delete(f"/leagues/{league.id}")
    assert response.status_code == 403
    assert await _count(session, League, id=league.id) == 1
    assert await _count(session, LeagueMember, league_id=league.id) == 2


@pytest.mark.asyncio
async def test_non_member_gets_not_found_not_forbidden(
    client, session, login, user_factory, league_factory, member_factory
):
    """A stranger must not be able to tell a real league id from a bogus one."""
    boss = await user_factory("boss3", sleeper_user_id="S20")
    stranger = await user_factory("stranger", sleeper_user_id="S21")
    league = await league_factory("Private")
    await member_factory(league, 1, "Boss", user=boss, role="commissioner")

    login(stranger)
    response = await client.delete(f"/leagues/{league.id}")
    assert response.status_code == 404
    assert await _count(session, League, id=league.id) == 1
