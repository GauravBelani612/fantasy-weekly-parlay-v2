import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy import select

from app.auth.session import CurrentUser, DbSession
from app.config import settings
from app.db import SessionLocal
from app.deps import RoundCtx
from app.models import League, LeagueMember, Leg, ParlayRound
from app.schemas import LegIn, LegOut, LegSettleIn, RoundOut
from app.serializers import leg_out, round_out
from app.services import legs as legs_service
from app.services import round_grading

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


@router.put("/me", response_model=RoundOut)
async def submit_my_leg(
    payload: LegIn,
    ctx: RoundCtx,
    user: CurrentUser,
    session: DbSession,
    background: BackgroundTasks,
):
    """Create or replace your single leg. Editable until the round locks."""
    leg = await legs_service.upsert_leg(session, ctx.round, ctx.member, payload.raw_text)
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
