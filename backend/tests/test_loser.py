"""Loser detection -- the single most important calculation in the app."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import ParlayRound
from app.services.rounds import (
    STATUS_LOCKED,
    STATUS_OPEN,
    STATUS_UPCOMING,
    compute_loser,
    resolve_loser,
    round_status,
)


def test_picks_the_single_lowest_scorer():
    result = compute_loser({1: 142.6, 2: 118.2, 3: 97.4, 4: 131.0})
    assert result.roster_id == 3
    assert result.points == 97.4
    assert not result.is_tie


def test_a_zero_score_is_a_real_score_and_loses():
    # A roster that started nobody scores 0.0 and absolutely should be on the hook.
    result = compute_loser({1: 88.0, 2: 0.0, 3: 101.5})
    assert result.roster_id == 2
    assert result.points == 0.0


def test_tie_is_reported_not_broken_silently():
    result = compute_loser({1: 100.0, 2: 88.5, 3: 88.5, 4: 120.0})
    assert result.is_tie
    assert result.roster_id is None, "a tie must never auto-assign a payer"
    assert result.tie_roster_ids == [2, 3]
    assert result.points == 88.5


def test_all_tied_is_still_a_tie():
    result = compute_loser({1: 90.0, 2: 90.0, 3: 90.0})
    assert result.is_tie
    assert result.tie_roster_ids == [1, 2, 3]


@pytest.mark.parametrize("scores", [{}, {1: 100.0}])
def test_refuses_to_pick_a_loser_without_a_real_league(scores):
    result = compute_loser(scores)
    assert result.roster_id is None
    assert result.tie_roster_ids == []


def test_negative_scores_are_handled():
    # Rare, but possible with fumble/INT penalties in some scoring settings.
    result = compute_loser({1: 12.0, 2: -3.5, 3: 40.0})
    assert result.roster_id == 2


def _round(opens_delta_h: float, locks_delta_h: float) -> ParlayRound:
    now = datetime.now(UTC)
    return ParlayRound(
        season="2025",
        scored_week=5,
        bet_week=6,
        opens_at=now + timedelta(hours=opens_delta_h),
        locks_at=now + timedelta(hours=locks_delta_h),
    )


def test_round_status_is_derived_from_the_clock():
    assert round_status(_round(opens_delta_h=1, locks_delta_h=48)) == STATUS_UPCOMING
    assert round_status(_round(opens_delta_h=-24, locks_delta_h=24)) == STATUS_OPEN
    assert round_status(_round(opens_delta_h=-72, locks_delta_h=-1)) == STATUS_LOCKED


def test_round_status_tolerates_naive_datetimes_from_sqlite():
    rnd = _round(-24, 24)
    rnd.opens_at = rnd.opens_at.replace(tzinfo=None)
    rnd.locks_at = rnd.locks_at.replace(tzinfo=None)
    assert round_status(rnd) == STATUS_OPEN


async def test_resolve_loser_maps_roster_to_member(
    session, league_factory, member_factory, monkeypatch
):
    league = await league_factory()
    await member_factory(league, 1, "Alice")
    bob = await member_factory(league, 2, "Bob")
    await member_factory(league, 3, "Carol")

    async def fake_matchups(_league_id, _week):
        return [
            {"roster_id": 1, "points": 120.5},
            {"roster_id": 2, "points": 71.2},
            {"roster_id": 3, "points": 99.9},
        ]

    monkeypatch.setattr("app.services.rounds.sleeper.get_matchups", fake_matchups)

    rnd = _round(-24, 24)
    rnd.league_id = league.id
    session.add(rnd)
    await session.flush()

    result = await resolve_loser(session, league, rnd)

    assert result.roster_id == 2
    assert rnd.loser_member_id == bob.id
    assert rnd.loser_points == 71.2
    assert rnd.tie_roster_ids is None


async def test_null_points_rosters_are_ignored(
    session, league_factory, member_factory, monkeypatch
):
    """A roster Sleeper has no score for must not be crowned the loser at 0."""
    league = await league_factory()
    await member_factory(league, 1, "Alice")
    await member_factory(league, 2, "Bob")
    carol = await member_factory(league, 3, "Carol")

    async def fake_matchups(_league_id, _week):
        return [
            {"roster_id": 1, "points": 110.0},
            {"roster_id": 2, "points": None},
            {"roster_id": 3, "points": 88.0},
        ]

    monkeypatch.setattr("app.services.rounds.sleeper.get_matchups", fake_matchups)

    rnd = _round(-24, 24)
    rnd.league_id = league.id
    session.add(rnd)
    await session.flush()

    result = await resolve_loser(session, league, rnd)
    assert result.roster_id == 3
    assert rnd.loser_member_id == carol.id
