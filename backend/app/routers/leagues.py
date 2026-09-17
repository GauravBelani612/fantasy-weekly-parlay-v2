import dataclasses

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth.session import CurrentUser, DbSession
from app.deps import LeagueCtx
from app.integrations.sleeper import avatar_url
from app.models import LeagueMember, SleeperLink
from app.schemas import (
    ImportLeagueIn,
    LeagueDetailOut,
    LeagueOut,
    LeagueSettingsIn,
    LeagueStatsOut,
)
from app.serializers import league_detail_out, league_out
from app.services import leagues as leagues_service
from app.services import stats as stats_service

router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get("", response_model=list[LeagueOut])
async def list_my_leagues(user: CurrentUser, session: DbSession):
    leagues = await leagues_service.get_user_leagues(session, user)
    out = []
    for league in leagues:
        member = await leagues_service.get_membership(session, league.id, user)
        out.append(league_out(league, member.role if member else None))
    return out


@router.post("/import", response_model=LeagueDetailOut, status_code=status.HTTP_201_CREATED)
async def import_league(payload: ImportLeagueIn, user: CurrentUser, session: DbSession):
    link = await session.get(SleeperLink, user.id)
    if link is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Link your Sleeper account before importing a league."
        )

    league = await leagues_service.import_league(session, user, payload.sleeper_league_id)

    members = list(
        (
            await session.scalars(
                select(LeagueMember).where(LeagueMember.league_id == league.id)
            )
        ).all()
    )
    if not any(m.user_id == user.id for m in members):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You do not own a roster in that league, so it cannot be imported by you.",
        )
    return league_detail_out(league, members, user)


@router.get("/{league_id}", response_model=LeagueDetailOut)
async def get_league(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    members = list(
        (
            await session.scalars(
                select(LeagueMember).where(LeagueMember.league_id == ctx.league.id)
            )
        ).all()
    )
    return league_detail_out(ctx.league, members, user)


@router.get("/{league_id}/stats", response_model=LeagueStatsOut)
async def get_league_stats(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    """League and personal stats for the season, recomputed from stored results."""
    stats = await stats_service.league_stats(session, ctx.league, user.id, avatar_url)
    return LeagueStatsOut.model_validate(dataclasses.asdict(stats))


@router.post("/{league_id}/sync", response_model=LeagueDetailOut)
async def sync_league(ctx: LeagueCtx, user: CurrentUser, session: DbSession):
    """Re-pull rosters and users from Sleeper (new managers, renamed teams, new claims)."""
    members = await leagues_service.sync_members(session, ctx.league)
    await session.commit()
    return league_detail_out(ctx.league, members, user)


@router.delete("/{league_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_league(ctx: LeagueCtx, session: DbSession) -> None:
    """Remove a league entirely -- commissioner only.

    This is league-wide, not "leave the league": it takes the board away from everyone in
    it, which is what you want for a league imported by mistake. Sleeper is unaffected, so
    a league deleted here can simply be imported again.
    """
    ctx.require_commissioner()
    await leagues_service.delete_league(session, ctx.league)


@router.patch("/{league_id}/settings", response_model=LeagueOut)
async def update_settings(payload: LeagueSettingsIn, ctx: LeagueCtx, session: DbSession):
    ctx.require_commissioner()
    league = ctx.league

    data = payload.model_dump(exclude_unset=True)
    for field in (
        "lock_offset_minutes",
        "timezone",
        "first_scored_week",
        "last_scored_week",
        "discord_webhook_url",
    ):
        if field in data:
            setattr(league, field, data[field])

    if league.first_scored_week > league.last_scored_week:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "first_scored_week must be less than or equal to last_scored_week.",
        )

    session.add(league)
    await session.commit()
    await session.refresh(league)
    return league_out(league, ctx.member.role)
