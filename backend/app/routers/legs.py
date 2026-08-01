from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.session import CurrentUser, DbSession
from app.deps import RoundCtx
from app.models import LeagueMember
from app.schemas import LegIn, LegOut, RoundOut
from app.serializers import leg_out, round_out
from app.services import legs as legs_service

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


@router.put("/me", response_model=RoundOut)
async def submit_my_leg(
    payload: LegIn, ctx: RoundCtx, user: CurrentUser, session: DbSession
):
    """Create or replace your single leg. Editable until the round locks."""
    await legs_service.upsert_leg(session, ctx.round, ctx.member, payload.raw_text)
    return await round_out(session, ctx.league, ctx.round, user)


@router.delete("/me", response_model=RoundOut)
async def delete_my_leg(ctx: RoundCtx, user: CurrentUser, session: DbSession):
    removed = await legs_service.delete_leg(session, ctx.round, ctx.member)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You have not submitted a leg yet.")
    return await round_out(session, ctx.league, ctx.round, user)
