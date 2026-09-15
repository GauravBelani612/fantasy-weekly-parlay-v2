"""The cached ESPN schedule has to survive the request that fetched it.

sync_week_schedule only flushes, and nothing downstream of get_session commits, so every
path through ensure_current_round that opens no round used to discard the weeks it had
just fetched. Nothing failed visibly -- the app simply re-fetched ESPN on every request
for the whole preseason, all of the end of season, and any league waiting on its first
scored week. These tests fail if that regresses.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.integrations import espn, sleeper
from app.models import NflWeek
from app.services import rounds as rounds_service


def _week(season: str, week: int, *, final: bool) -> espn.WeekSchedule:
    kick = datetime(2026, 9, 10, tzinfo=UTC) + timedelta(days=7 * week)
    events = [
        espn.NflEvent(
            event_id=f"{season}-{week}-{i}",
            name=f"Game {i}",
            kickoff_at=kick + timedelta(hours=i),
            status="STATUS_FINAL" if final else "STATUS_SCHEDULED",
        )
        for i in range(3)
    ]
    return espn.WeekSchedule(season=season, week=week, events=events)


@pytest.fixture
def espn_calls(monkeypatch):
    """Count ESPN fetches, and report no week as final so no round can open."""
    calls: list[tuple[str, int]] = []

    async def fake_schedule(season: str, week: int) -> espn.WeekSchedule:
        calls.append((season, week))
        return _week(season, week, final=False)

    async def fake_state() -> dict:
        return {"season": "2026", "week": 3, "season_type": "regular"}

    monkeypatch.setattr(espn, "get_week_schedule", fake_schedule)
    monkeypatch.setattr(sleeper, "get_nfl_state", fake_state)
    return calls


@pytest.mark.asyncio
async def test_schedule_survives_a_request_that_opens_no_round(
    session, league_factory, espn_calls
):
    league = await league_factory(season="2026")

    assert await rounds_service.ensure_current_round(session, league) is None
    assert espn_calls, "expected ESPN to be consulted"

    # Discard anything still uncommitted. Rows written only by flush vanish here, which
    # is exactly what used to happen when the request's session closed.
    await session.rollback()

    cached = (await session.execute(select(func.count()).select_from(NflWeek))).scalar_one()
    assert cached > 0, "the fetched weeks were rolled back instead of cached"


@pytest.mark.asyncio
async def test_second_request_reuses_the_cache_instead_of_refetching(
    session, league_factory, espn_calls
):
    league = await league_factory(season="2026")

    await rounds_service.ensure_current_round(session, league)
    first = len(espn_calls)
    assert first > 0

    await rounds_service.ensure_current_round(session, league)

    assert len(espn_calls) == first, (
        "ESPN was consulted again inside the TTL -- the cache is not being read, "
        f"{first} calls became {len(espn_calls)}"
    )


@pytest.mark.asyncio
async def test_a_finished_week_is_cached_permanently(session, monkeypatch):
    """A week that is over can never change, so it must never be re-fetched."""
    calls: list[int] = []

    async def fake_schedule(season: str, week: int) -> espn.WeekSchedule:
        calls.append(week)
        return _week(season, week, final=True)

    monkeypatch.setattr(espn, "get_week_schedule", fake_schedule)

    row = await rounds_service.sync_week_schedule(session, "2026", 1)
    assert row is not None and row.all_final
    await session.commit()

    # Push the fetch well outside the live TTL; a final week must still not re-fetch.
    row.fetched_at = datetime.now(UTC) - timedelta(days=30)
    session.add(row)
    await session.commit()

    await rounds_service.sync_week_schedule(session, "2026", 1)
    assert calls == [1], "a finished week was re-fetched despite being unchangeable"
