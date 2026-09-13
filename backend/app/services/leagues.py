"""Importing and syncing a Sleeper league into local tables."""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import sleeper
from app.models import (
    League,
    LeagueMember,
    Leg,
    NotificationLog,
    ParlayRound,
    SleeperLink,
    User,
    WeekScore,
)

log = logging.getLogger(__name__)


async def _claimed_user_by_sleeper_id(session: AsyncSession) -> dict[str, SleeperLink]:
    rows = (await session.scalars(select(SleeperLink))).all()
    return {link.sleeper_user_id: link for link in rows}


async def import_league(session: AsyncSession, user: User, sleeper_league_id: str) -> League:
    """Create (or refresh) a league and a member row for every Sleeper roster.

    The importing user becomes commissioner. Rosters belonging to people who have not signed
    up still get member rows with user_id NULL -- they cannot submit legs, but they must be
    present for the lowest-score calculation to see the whole league.
    """
    raw_league = await sleeper.get_league(sleeper_league_id)
    if not raw_league:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That Sleeper league was not found")

    season = str(raw_league.get("season") or "")
    existing = await session.scalar(
        select(League).where(
            League.sleeper_league_id == sleeper_league_id, League.season == season
        )
    )

    league = existing or League(
        sleeper_league_id=sleeper_league_id,
        season=season,
        created_by_user_id=user.id,
    )
    league.name = raw_league.get("name") or "Untitled League"
    league.avatar = raw_league.get("avatar")
    league.total_rosters = int(raw_league.get("total_rosters") or 0)
    league.synced_at = datetime.now(UTC)
    session.add(league)
    await session.flush()

    await sync_members(session, league, commissioner_user=user if existing is None else None)
    await session.commit()
    await session.refresh(league)
    return league


async def sync_members(
    session: AsyncSession, league: League, commissioner_user: User | None = None
) -> list[LeagueMember]:
    """Reconcile league_members against Sleeper's current rosters and users."""
    rosters = await sleeper.get_league_rosters(league.sleeper_league_id)
    users = await sleeper.get_league_users(league.sleeper_league_id)
    users_by_id = {str(u["user_id"]): u for u in users if u.get("user_id")}
    links = await _claimed_user_by_sleeper_id(session)

    existing = {
        m.sleeper_roster_id: m
        for m in (
            await session.scalars(select(LeagueMember).where(LeagueMember.league_id == league.id))
        ).all()
    }

    members: list[LeagueMember] = []
    for roster in rosters:
        roster_id = roster.get("roster_id")
        if roster_id is None:
            continue
        owner_id = str(roster["owner_id"]) if roster.get("owner_id") else None
        owner = users_by_id.get(owner_id or "", {})
        metadata = owner.get("metadata") or {}

        member = existing.get(roster_id) or LeagueMember(
            league_id=league.id, sleeper_roster_id=roster_id
        )
        member.sleeper_user_id = owner_id
        member.display_name = owner.get("display_name") or f"Roster {roster_id}"
        member.team_name = metadata.get("team_name")
        member.avatar = owner.get("avatar")

        # Attach the app account if this Sleeper user has been claimed.
        link = links.get(owner_id) if owner_id else None
        if link is not None:
            member.user_id = link.user_id

        if commissioner_user is not None and member.user_id == commissioner_user.id:
            member.role = "commissioner"

        session.add(member)
        members.append(member)

    league.total_rosters = len(members) or league.total_rosters
    league.synced_at = datetime.now(UTC)
    await session.flush()
    return members


async def attach_user_to_leagues(session: AsyncSession, user: User, sleeper_user_id: str) -> int:
    """Back-fill user_id on member rows after someone claims a Sleeper account.

    Without this, a member who joins the app after their league was imported would stay
    unlinked and be unable to submit a leg.
    """
    rows = (
        await session.scalars(
            select(LeagueMember).where(
                LeagueMember.sleeper_user_id == sleeper_user_id,
                LeagueMember.user_id.is_(None),
            )
        )
    ).all()
    for member in rows:
        member.user_id = user.id
        session.add(member)
    await session.flush()
    return len(rows)


async def get_user_leagues(session: AsyncSession, user: User) -> list[League]:
    stmt = (
        select(League)
        .join(LeagueMember, LeagueMember.league_id == League.id)
        .where(LeagueMember.user_id == user.id)
        .order_by(League.season.desc(), League.name)
    )
    return list((await session.scalars(stmt)).unique().all())


async def get_membership(
    session: AsyncSession, league_id, user: User
) -> LeagueMember | None:
    return await session.scalar(
        select(LeagueMember).where(
            LeagueMember.league_id == league_id, LeagueMember.user_id == user.id
        )
    )


async def delete_league(session: AsyncSession, league: League) -> None:
    """Delete a league and everything hanging off it.

    Children are removed explicitly rather than leaning on ON DELETE CASCADE. The foreign
    keys do declare it, and Postgres honours it -- but SQLite ignores foreign keys entirely
    unless PRAGMA foreign_keys is turned on, which this app never does, and both local dev
    and the test suite run on SQLite. Deleting by hand behaves the same on both.

    Order matters: rounds go before members, because parlay_rounds.loser_member_id points
    at league_members.
    """
    round_ids = select(ParlayRound.id).where(ParlayRound.league_id == league.id)

    await session.execute(delete(Leg).where(Leg.round_id.in_(round_ids)))
    await session.execute(delete(NotificationLog).where(NotificationLog.round_id.in_(round_ids)))
    await session.execute(delete(ParlayRound).where(ParlayRound.league_id == league.id))
    await session.execute(delete(WeekScore).where(WeekScore.league_id == league.id))
    await session.execute(delete(LeagueMember).where(LeagueMember.league_id == league.id))
    await session.execute(delete(League).where(League.id == league.id))
    await session.commit()
