from fastapi import APIRouter, HTTPException, status

from app.auth.session import CurrentUser, DbSession
from app.deps import LeagueCtx, RoundCtx
from app.models import LeagueMember
from app.schemas import RoundOut, RoundResultIn, SetLoserIn
from app.serializers import round_out
from app.services import rounds as rounds_service

router = APIRouter(tags=["rounds"])


@router.get("/leagues/{league_id}/rounds/current", response_model=RoundOut | None)
async def get_current_round(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    """The round the league should be filling in right now.

    Returns null during the preseason, or before the league's first scored week has
    finished -- there is simply nothing to bet on yet.
    """
    rnd = await rounds_service.ensure_current_round(session, ctx.league)
    if rnd is None:
        return None
    return await round_out(session, ctx.league, rnd, user)


@router.get("/leagues/{league_id}/rounds", response_model=list[RoundOut])
async def list_league_rounds(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    rounds = await rounds_service.list_rounds(session, ctx.league)
    return [await round_out(session, ctx.league, rnd, user) for rnd in rounds]


@router.get("/rounds/{round_id}", response_model=RoundOut)
async def get_round(ctx: RoundCtx, user: CurrentUser, session: DbSession):
    return await round_out(session, ctx.league, ctx.round, user)


@router.post("/rounds/{round_id}/loser", response_model=RoundOut)
async def set_round_loser(
    payload: SetLoserIn, ctx: RoundCtx, user: CurrentUser, session: DbSession
):
    """Resolve a tied week. Ties are never broken automatically."""
    ctx.require_commissioner()

    member = await session.get(LeagueMember, payload.member_id)
    if member is None or member.league_id != ctx.league.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That member is not in this league.")

    rnd = await rounds_service.set_loser_manually(session, ctx.round, member.id)
    return await round_out(session, ctx.league, rnd, user)


@router.patch("/rounds/{round_id}/result", response_model=RoundOut)
async def record_round_result(
    payload: RoundResultIn, ctx: RoundCtx, user: CurrentUser, session: DbSession
):
    """Record what actually happened. Only the person who funded it, or the commissioner."""
    rnd = ctx.round
    is_loser = rnd.loser_member_id is not None and rnd.loser_member_id == ctx.member.id
    if not (is_loser or ctx.is_commissioner):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the commissioner or the player who funded this parlay can record the result.",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rnd, field, value)

    session.add(rnd)
    await session.commit()
    await session.refresh(rnd)
    return await round_out(session, ctx.league, rnd, user)


@router.post("/leagues/{league_id}/rounds/refresh", response_model=RoundOut | None)
async def refresh_current_round(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    """Force a re-check of scores and schedule (useful right after Monday night)."""
    from app.integrations import sleeper

    sleeper.clear_state_cache()
    rnd = await rounds_service.ensure_current_round(session, ctx.league)
    if rnd is None:
        return None
    if rnd.tie_roster_ids is None and rnd.loser_member_id is None:
        await rounds_service.resolve_loser(session, ctx.league, rnd)
        await session.commit()
    return await round_out(session, ctx.league, rnd, user)
