"""Shared route dependencies: load a league/round and authorize the caller in one step."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session import CurrentUser, DbSession
from app.models import League, LeagueMember, ParlayRound
from app.services.leagues import get_membership


@dataclass
class LeagueContext:
    league: League
    member: LeagueMember

    @property
    def is_commissioner(self) -> bool:
        return self.member.role == "commissioner"

    def require_commissioner(self) -> None:
        if not self.is_commissioner:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only the league commissioner can do that."
            )


async def _load_league_context(
    session: AsyncSession, league_id: uuid.UUID, user
) -> LeagueContext:
    league = await session.get(League, league_id)
    if league is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "League not found")
    member = await get_membership(session, league.id, user)
    if member is None:
        # Same response as "not found" so league IDs cannot be probed.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "League not found")
    return LeagueContext(league=league, member=member)


async def get_league_context(
    session: DbSession,
    user: CurrentUser,
    league_id: Annotated[uuid.UUID, Path()],
) -> LeagueContext:
    return await _load_league_context(session, league_id, user)


@dataclass
class RoundContext(LeagueContext):
    round: ParlayRound


async def get_round_context(
    session: DbSession,
    user: CurrentUser,
    round_id: Annotated[uuid.UUID, Path()],
) -> RoundContext:
    rnd = await session.get(ParlayRound, round_id)
    if rnd is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Round not found")
    ctx = await _load_league_context(session, rnd.league_id, user)
    return RoundContext(league=ctx.league, member=ctx.member, round=rnd)


LeagueCtx = Annotated[LeagueContext, Depends(get_league_context)]
RoundCtx = Annotated[RoundContext, Depends(get_round_context)]
