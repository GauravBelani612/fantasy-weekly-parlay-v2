import asyncio
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.auth.session import CurrentUser, DbSession
from app.config import settings
from app.db import SessionLocal
from app.deps import RoundCtx
from app.integrations import espn
from app.models import League, LeagueMember, Leg, ParlayRound
from app.schemas import LegIn, LegOut, LegSettleIn, RoundOut
from app.serializers import leg_out, round_out
from app.services import grading, leg_parser, leg_rules, round_grading
from app.services import legs as legs_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/rounds/{round_id}/legs", tags=["legs"])


@router.get("", response_model=list[LegOut])
async def list_round_legs(ctx: RoundCtx, session: DbSession):
    """Every leg in the round. Visible to the whole league as soon as they land."""
    legs = await legs_service.list_legs(session, ctx.round)
    # Load members explicitly -- touching ctx.league.members would trigger a lazy load
    # outside the async greenlet context and blow up at runtime.
    members = {
        m.id: m
        for m in (
            await session.scalars(
                select(LeagueMember).where(LeagueMember.league_id == ctx.league.id)
            )
        ).all()
    }
    return [leg_out(leg, members.get(leg.member_id), ctx.member.user_id) for leg in legs]


async def _read_round(round_id: uuid.UUID) -> None:
    """Read a just-submitted leg straight away, after the response has gone out.

    So the submitter sees how their leg was understood while they can still fix it,
    rather than only after the next tick. Runs in its own session: the request's has
    closed by now. Anything that fails here is simply picked up by the tick.
    """
    try:
        async with SessionLocal() as session:
            rnd = await session.get(ParlayRound, round_id)
            league = await session.get(League, rnd.league_id) if rnd else None
            if rnd is None or league is None:
                return
            await round_grading.grade_round(session, league, rnd, settings.public_app_url)
    except Exception:
        log.exception("Background read of round %s failed; the tick will retry", round_id)


# Someone is watching a spinner for the length of this, so it is capped well below what
# the tick allows itself. Past the cap the leg is taken unread and read again later.
_READ_BUDGET_SECONDS = 12.0


async def _read_and_schedule(
    text: str, rnd: ParlayRound
) -> tuple[dict | None, espn.WeekSchedule | None]:
    schedule = await espn.get_week_schedule(rnd.season, rnd.bet_week)
    matchups = [event.name for event in schedule.events]
    # Tighter than parse_leg's own defaults, which are sized for a background sweep: three
    # attempts at thirty seconds would leave the submitter hanging for a minute and a half.
    parsed = await leg_parser.parse_leg(
        text, matchups, rnd.bet_week, timeout=8.0, max_retries=1
    )
    # Both rules key off which game the leg rides on, so the team has to be right before
    # either one runs -- the model guesses at it, and a wrong guess would refuse a legal leg.
    if grading.names_a_player(parsed):
        parsed = grading.with_real_team(parsed, grading.roster_index(await espn.get_rosters()))
    return parsed, schedule


async def _read_before_accepting(
    text: str, rnd: ParlayRound
) -> tuple[dict | None, espn.WeekSchedule | None]:
    """Read a leg up front, so it can be refused while its author is still looking at it.

    Best effort by design. If ESPN or the model is slow or unreachable we return nothing,
    the leg is accepted unread and the tick reads it later. Turning submissions away
    because an upstream is having a bad minute would be a worse rule than letting a
    duplicate through -- the duplicate costs an argument, the refusal costs someone their
    week.
    """
    if not settings.anthropic_api_key:
        return None, None
    try:
        return await asyncio.wait_for(
            _read_and_schedule(text, rnd), timeout=_READ_BUDGET_SECONDS
        )
    except TimeoutError:
        log.warning("Reading a leg ran past %ss; taking it unread", _READ_BUDGET_SECONDS)
    except Exception:
        log.exception("Could not read a leg before accepting it; taking it unread")
    return None, None


@router.put("/me", response_model=RoundOut)
async def submit_my_leg(
    payload: LegIn,
    ctx: RoundCtx,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
):
    """Create or replace your single leg. Editable until the round locks."""
    # Checked before anything is read: no reason to spend a model call on a leg the round
    # will not take anyway.
    legs_service.assert_submittable(ctx.round)
    text = legs_service.clean_text(payload.raw_text)

    parsed, schedule = await _read_before_accepting(text, ctx.round)
    if refusal := await leg_rules.refusal(session, ctx.round, ctx.member, parsed, schedule):
        raise HTTPException(status.HTTP_409_CONFLICT, refusal)

    leg = await legs_service.upsert_leg(session, ctx.round, ctx.member, text, parsed=parsed)
    # Skipped without a key: there is nothing to read with, and it keeps the test suite
    # from reaching for the network.
    if leg.parsed is None and settings.anthropic_api_key:
        background.add_task(_read_round, ctx.round.id)
    return await round_out(session, ctx.league, ctx.round, user)


@router.patch("/{leg_id}", response_model=RoundOut)
async def settle_leg(
    leg_id: uuid.UUID,
    payload: LegSettleIn,
    ctx: RoundCtx,
    user: CurrentUser,
    session: DbSession,
):
    """Record the line a leg was placed at, or settle it by hand.

    Only the player funding the parlay or the commissioner: the payer is the one who
    saw the real sportsbook line, and the commissioner settles disputes.
    """
    rnd = ctx.round
    is_payer = rnd.loser_member_id is not None and rnd.loser_member_id == ctx.member.id
    if not (is_payer or ctx.is_commissioner):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the commissioner or the player funding this parlay can settle legs.",
        )

    leg = await session.get(Leg, leg_id)
    if leg is None or leg.round_id != rnd.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That leg is not in this round.")

    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "Send a line, a result, or both.")

    await round_grading.set_leg(
        session, ctx.league, rnd, leg, ctx.member, changes, settings.public_app_url
    )
    return await round_out(session, ctx.league, rnd, user)


@router.delete("/me", response_model=RoundOut)
async def delete_my_leg(ctx: RoundCtx, user: CurrentUser, session: DbSession):
    removed = await legs_service.delete_leg(session, ctx.round, ctx.member)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You have not submitted a leg yet.")
    return await round_out(session, ctx.league, ctx.round, user)
