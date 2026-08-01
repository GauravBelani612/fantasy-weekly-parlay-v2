"""Round lifecycle: who lost, what week the legs are for, and when submissions lock.

Design note: a round's open/locked state is *derived* from timestamps on every read, never
stored as a mutable flag that a background job has to flip. If the cron never fires, the app
is still correct -- you just do not get an email. That matters on a free tier where the API
sleeps and the scheduler is best-effort.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import espn, sleeper
from app.models import League, LeagueMember, NflWeek, ParlayRound, WeekScore

log = logging.getLogger(__name__)

# How long a not-yet-final week's schedule may be reused before we re-check ESPN.
_LIVE_SCHEDULE_TTL = timedelta(minutes=15)
# Bound how far back we scan for the most recent completed week.
_MAX_LOOKBACK_WEEKS = 3

STATUS_UPCOMING = "upcoming"
STATUS_OPEN = "open"
STATUS_LOCKED = "locked"


@dataclass(frozen=True)
class LoserResult:
    roster_id: int | None
    points: float | None
    tie_roster_ids: list[int]

    @property
    def is_tie(self) -> bool:
        return len(self.tie_roster_ids) > 1


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; normalize before comparing."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def round_status(rnd: ParlayRound, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if now >= _as_utc(rnd.locks_at):
        return STATUS_LOCKED
    if now >= _as_utc(rnd.opens_at):
        return STATUS_OPEN
    return STATUS_UPCOMING


async def sync_week_schedule(session: AsyncSession, season: str, week: int) -> NflWeek | None:
    """Cache one NFL week's kickoff window and finality, refreshing only when stale."""
    cached = await session.get(NflWeek, (season, week))
    if cached is not None:
        # A finished week never changes, so it is cached permanently.
        if cached.all_final:
            return cached
        if datetime.now(UTC) - _as_utc(cached.fetched_at) < _LIVE_SCHEDULE_TTL:
            return cached

    schedule = await espn.get_week_schedule(season, week)
    if not schedule.events:
        return cached

    row = cached or NflWeek(season=season, week=week)
    row.first_kickoff_at = schedule.first_kickoff_at
    row.last_kickoff_at = schedule.last_kickoff_at
    row.event_count = len(schedule.events)
    row.all_final = schedule.all_final
    row.fetched_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return row


async def latest_final_week(session: AsyncSession, season: str, hint_week: int) -> int | None:
    """Highest week that ESPN reports as fully complete.

    Deriving the round from schedule finality rather than Sleeper's `state.week` makes this
    self-correcting: Sleeper flips its week pointer on its own schedule, but a week is only
    scorable once every game in it is actually over.
    """
    start = min(hint_week, espn.MAX_REGULAR_WEEK)
    for week in range(start, max(start - _MAX_LOOKBACK_WEEKS, 0), -1):
        nfl_week = await sync_week_schedule(session, season, week)
        if nfl_week is not None and nfl_week.all_final:
            return week
    return None


async def sync_week_scores(session: AsyncSession, league: League, week: int) -> dict[int, float]:
    """Pull Sleeper matchup points for a week and cache them for auditability."""
    matchups = await sleeper.get_matchups(league.sleeper_league_id, week)

    scores: dict[int, float] = {}
    for entry in matchups:
        roster_id = entry.get("roster_id")
        points = entry.get("points")
        # A null score means Sleeper has nothing for that roster; 0.0 is a real score and
        # must be kept, since a zero week is exactly the kind of week that loses.
        if roster_id is None or points is None:
            continue
        scores[int(roster_id)] = float(points)

    existing = {
        row.sleeper_roster_id: row
        for row in (
            await session.scalars(
                select(WeekScore).where(
                    WeekScore.league_id == league.id,
                    WeekScore.season == league.season,
                    WeekScore.week == week,
                )
            )
        ).all()
    }
    now = datetime.now(UTC)
    for roster_id, points in scores.items():
        row = existing.get(roster_id) or WeekScore(
            league_id=league.id, season=league.season, week=week, sleeper_roster_id=roster_id
        )
        row.points = points
        row.fetched_at = now
        session.add(row)
    await session.flush()
    return scores


def compute_loser(scores: dict[int, float]) -> LoserResult:
    """Lowest total points in the league that week.

    A tie is never broken silently -- it is reported so a human can settle it.
    """
    if len(scores) < 2:
        return LoserResult(roster_id=None, points=None, tie_roster_ids=[])

    lowest = min(scores.values())
    tied = sorted(rid for rid, pts in scores.items() if pts == lowest)
    if len(tied) > 1:
        return LoserResult(roster_id=None, points=lowest, tie_roster_ids=tied)
    return LoserResult(roster_id=tied[0], points=lowest, tie_roster_ids=[])


async def ensure_current_round(session: AsyncSession, league: League) -> ParlayRound | None:
    """Create or refresh the round the league should currently be filling in.

    scored_week decides who pays; bet_week (scored_week + 1) is what the legs are on.
    """
    state = await sleeper.get_nfl_state()
    season = str(state.get("season") or league.season)
    if season != league.season:
        # League is from a past season; nothing new to open.
        return await get_latest_round(session, league)

    hint_week = int(state.get("week") or 0)
    if hint_week <= 0:
        return await get_latest_round(session, league)  # preseason

    scored_week = await latest_final_week(session, season, hint_week)
    if scored_week is None or scored_week < league.first_scored_week:
        return await get_latest_round(session, league)
    if scored_week > league.last_scored_week:
        return await get_latest_round(session, league)

    bet_week = scored_week + 1
    if bet_week > espn.MAX_REGULAR_WEEK:
        return await get_latest_round(session, league)

    bet_schedule = await sync_week_schedule(session, season, bet_week)
    if bet_schedule is None or bet_schedule.first_kickoff_at is None:
        return await get_latest_round(session, league)

    locks_at = _as_utc(bet_schedule.first_kickoff_at) - timedelta(
        minutes=league.lock_offset_minutes
    )

    rnd = await session.scalar(
        select(ParlayRound).where(
            ParlayRound.league_id == league.id,
            ParlayRound.season == season,
            ParlayRound.bet_week == bet_week,
        )
    )
    is_new = rnd is None
    if is_new:
        rnd = ParlayRound(
            league_id=league.id,
            season=season,
            scored_week=scored_week,
            bet_week=bet_week,
            opens_at=datetime.now(UTC),
            locks_at=locks_at,
        )
        session.add(rnd)

    # Deadline can move if ESPN reschedules a game (flex, weather).
    rnd.locks_at = locks_at

    if rnd.loser_member_id is None:
        await resolve_loser(session, league, rnd)

    await session.commit()
    await session.refresh(rnd)
    return rnd


async def resolve_loser(session: AsyncSession, league: League, rnd: ParlayRound) -> LoserResult:
    """Compute and persist who funds this round."""
    scores = await sync_week_scores(session, league, rnd.scored_week)
    result = compute_loser(scores)

    rnd.loser_points = result.points
    rnd.tie_roster_ids = result.tie_roster_ids or None

    if result.roster_id is not None:
        member = await session.scalar(
            select(LeagueMember).where(
                LeagueMember.league_id == league.id,
                LeagueMember.sleeper_roster_id == result.roster_id,
            )
        )
        rnd.loser_member_id = member.id if member else None
    session.add(rnd)
    await session.flush()
    return result


async def set_loser_manually(
    session: AsyncSession, rnd: ParlayRound, member_id: uuid.UUID
) -> ParlayRound:
    """Commissioner resolution for a tied week."""
    rnd.loser_member_id = member_id
    rnd.tie_roster_ids = None
    session.add(rnd)
    await session.commit()
    await session.refresh(rnd)
    return rnd


async def get_latest_round(session: AsyncSession, league: League) -> ParlayRound | None:
    return await session.scalar(
        select(ParlayRound)
        .where(ParlayRound.league_id == league.id)
        .order_by(ParlayRound.season.desc(), ParlayRound.bet_week.desc())
        .limit(1)
    )


async def list_rounds(session: AsyncSession, league: League) -> list[ParlayRound]:
    stmt = (
        select(ParlayRound)
        .where(ParlayRound.league_id == league.id)
        .order_by(ParlayRound.season.desc(), ParlayRound.bet_week.desc())
    )
    return list((await session.scalars(stmt)).all())
