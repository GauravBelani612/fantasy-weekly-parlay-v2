"""Reading and settling a round's legs as its games finish.

Runs from the tick, and again straight away whenever the payer or commissioner changes a
leg. Everything that can be re-derived is: an unread leg is read, an unsettled leg is
graded again, and the parlay is settled from its legs. A result a person set by hand is
never touched by the grader.

Two rules decide the parlay's outcome, and they differ on purpose. The grader only ever
moves a parlay out of "pending" -- it will not overturn an outcome that is already settled.
A person correcting a leg is different: they are saying the legs were wrong, so the outcome
follows the legs again, back to pending if need be. Without that, one misgraded leg on a
Thursday would leave the parlay stuck at "lost" even after every leg cashed.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import espn
from app.models import League, LeagueMember, Leg, ParlayRound
from app.services import grading, leg_parser, notify
from app.services import legs as legs_service

log = logging.getLogger(__name__)

# How long after the lock a round keeps being graded automatically. Games run Thursday to
# Monday, so this leaves several days of slack for a late line or a stat correction. Past
# it the grader stops spending ESPN calls on the round; hand overrides still work.
GRADE_WINDOW = timedelta(days=10)

SETTLED = ("won", "lost", "void")


class _WeekCache:
    """Scoreboards and box scores fetched once per pass, however many legs need them."""

    def __init__(self) -> None:
        self._schedules: dict[tuple[str, int], espn.WeekSchedule] = {}
        self._summaries: dict[str, espn.GameSummary | None] = {}

    async def schedule(self, season: str, week: int) -> espn.WeekSchedule:
        key = (season, week)
        if key not in self._schedules:
            self._schedules[key] = await espn.get_week_schedule(season, week)
        return self._schedules[key]

    async def summary(self, event_id: str) -> espn.GameSummary | None:
        if event_id not in self._summaries:
            self._summaries[event_id] = await espn.get_game_summary(event_id)
        return self._summaries[event_id]


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def rounds_to_grade(session: AsyncSession, league: League) -> list[ParlayRound]:
    """Rounds whose legs can still change: open ones, and those recently locked."""
    cutoff = _now() - GRADE_WINDOW
    stmt = select(ParlayRound).where(
        ParlayRound.league_id == league.id, ParlayRound.locks_at >= cutoff
    )
    return list((await session.scalars(stmt)).all())


def apply_grade(leg: Leg, grade: grading.Grade) -> bool:
    """Write a grade onto a leg. Returns whether anything changed."""
    settled = grade.result in grading.TERMINAL
    new = (
        grade.result,
        grade.detail,
        grade.event_id or leg.espn_event_id,
        "espn" if settled else None,
        grade.kickoff_at or leg.kickoff_at,
    )
    old = (leg.result, leg.grade_detail, leg.espn_event_id, leg.graded_by, leg.kickoff_at)
    if new == old:
        return False
    leg.result, leg.grade_detail, leg.espn_event_id, leg.graded_by, leg.kickoff_at = new
    leg.graded_at = _now() if settled else None
    return True


def _grader_owns(leg: Leg) -> bool:
    # A hand-set result is final, and so is anything already settled from a box score --
    # regrading on every tick would let a late stat correction flip a result the league
    # has already been emailed about.
    if leg.graded_by == "manual":
        return False
    return not (leg.graded_by == "espn" and leg.result in grading.TERMINAL)


async def grade_round(
    session: AsyncSession,
    league: League,
    rnd: ParlayRound,
    app_url: str,
    cache: _WeekCache | None = None,
) -> list[str]:
    """Read, grade and settle one round. Returns the notification kinds sent."""
    cache = cache or _WeekCache()
    legs = await legs_service.list_legs(session, rnd)
    if not legs:
        return []

    schedule = await cache.schedule(rnd.season, rnd.bet_week)
    matchups = [e.name for e in schedule.events]

    # Read concurrently: a fresh round can have a dozen unread legs, and doing them one at
    # a time would hold the tick open for most of a minute. parse_leg never raises.
    unread = [leg for leg in legs if leg_parser.needs_reading(leg.parsed)]
    readings = await asyncio.gather(
        *(leg_parser.parse_leg(leg.raw_text, matchups, rnd.bet_week) for leg in unread)
    )
    for leg, reading in zip(unread, readings, strict=True):
        leg.parsed = reading

    for leg in legs:
        if _grader_owns(leg):
            grade = await grading.grade_leg(leg.parsed, leg.payer_line, schedule, cache.summary)
            apply_grade(leg, grade)

    await session.commit()
    return await settle(session, league, rnd, app_url, follow_legs=False)


async def settle(
    session: AsyncSession,
    league: League,
    rnd: ParlayRound,
    app_url: str,
    *,
    follow_legs: bool,
) -> list[str]:
    """Settle the parlay from its legs, and announce it if that settles something new.

    follow_legs=False is the grader: it only moves a parlay out of pending.
    follow_legs=True is a person correcting a leg: the outcome tracks the legs, in either
    direction, so a wrong "lost" can become "won".
    """
    legs = await legs_service.list_legs(session, rnd)
    computed = grading.resolve_outcome([leg.result for leg in legs])

    if follow_legs:
        if rnd.outcome == computed:
            return []
    elif rnd.outcome != "pending" or computed == "pending":
        return []

    rnd.outcome = computed
    session.add(rnd)
    await session.commit()

    if computed not in SETTLED:
        return []
    return await notify.notify_resolution(session, league, rnd, app_url)


async def grade_league(session: AsyncSession, league: League, app_url: str) -> list[str]:
    """Every gradeable round in a league, sharing one fetch cache."""
    cache = _WeekCache()
    sent: list[str] = []
    for rnd in await rounds_to_grade(session, league):
        if _as_utc(rnd.opens_at) > _now():
            continue
        sent.extend(await grade_round(session, league, rnd, app_url, cache))
    return sent


async def set_leg(
    session: AsyncSession,
    league: League,
    rnd: ParlayRound,
    leg: Leg,
    member: LeagueMember,
    changes: dict,
    app_url: str,
) -> None:
    """The payer or commissioner recording a line, or settling a leg by hand."""
    if "line" in changes:
        leg.payer_line = changes["line"]
        if leg.graded_by != "manual":
            # A new line means a fresh grade; hand the leg back to the grader.
            leg.result, leg.grade_detail, leg.graded_by, leg.graded_at = (
                grading.PENDING, None, None, None,
            )

    if "result" in changes:
        result = changes["result"]
        if result == grading.PENDING:
            leg.result, leg.grade_detail, leg.graded_by, leg.graded_at = (
                grading.PENDING, None, None, None,
            )
        else:
            leg.result = result
            leg.graded_by = "manual"
            leg.graded_at = _now()
            leg.grade_detail = f"Marked {result} by {member.display_name}"

    session.add(leg)
    await session.commit()

    # Grade straight away, so a line entered after the game settles on the spot rather
    # than at the next tick. Best effort: the tick will get there regardless.
    try:
        cache = _WeekCache()
        schedule = await cache.schedule(rnd.season, rnd.bet_week)
        if _grader_owns(leg):
            if leg_parser.needs_reading(leg.parsed):
                leg.parsed = await leg_parser.parse_leg(
                    leg.raw_text, [e.name for e in schedule.events], rnd.bet_week
                )
            apply_grade(
                leg, await grading.grade_leg(leg.parsed, leg.payer_line, schedule, cache.summary)
            )
            await session.commit()
    except Exception:
        log.exception("Immediate grade failed for leg %s; the tick will retry", leg.id)
        await session.rollback()

    await settle(session, league, rnd, app_url, follow_legs=True)
