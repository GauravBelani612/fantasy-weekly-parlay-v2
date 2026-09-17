"""Model -> schema conversion, kept in one place so every endpoint agrees on shape."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.sleeper import avatar_url
from app.models import League, LeagueMember, Leg, ParlayRound, User
from app.schemas import LeagueDetailOut, LeagueOut, LegOut, MemberOut, RoundOut
from app.services import grading
from app.services import legs as legs_service
from app.services.rounds import round_status


def member_out(member: LeagueMember, current_user_id: uuid.UUID | None = None) -> MemberOut:
    return MemberOut(
        id=member.id,
        display_name=member.display_name,
        team_name=member.team_name,
        avatar_url=avatar_url(member.avatar),
        sleeper_roster_id=member.sleeper_roster_id,
        role=member.role,
        has_app_account=member.user_id is not None,
        is_you=current_user_id is not None and member.user_id == current_user_id,
    )


def leg_out(
    leg: Leg, member: LeagueMember | None, current_user_id: uuid.UUID | None = None
) -> LegOut:
    return LegOut(
        id=leg.id,
        member_id=leg.member_id,
        member_name=member.display_name if member else "Unknown",
        member_avatar_url=avatar_url(member.avatar) if member else None,
        raw_text=leg.raw_text,
        result=leg.result,
        american_odds=leg.american_odds,
        created_at=leg.created_at,
        updated_at=leg.updated_at,
        is_you=bool(member and current_user_id and member.user_id == current_user_id),
        read_as=grading.read_as(leg.parsed, leg.payer_line),
        grade_detail=leg.grade_detail,
        graded_by=leg.graded_by,
        payer_line=leg.payer_line,
        # A leg settled by hand needs no line, whatever its text said.
        needs_line=leg.graded_by != "manual" and grading.needs_line(leg.parsed, leg.payer_line),
        kickoff_at=leg.kickoff_at,
    )


def league_out(league: League, your_role: str | None = None) -> LeagueOut:
    return LeagueOut(
        id=league.id,
        sleeper_league_id=league.sleeper_league_id,
        name=league.name,
        season=league.season,
        avatar_url=avatar_url(league.avatar),
        total_rosters=league.total_rosters,
        lock_offset_minutes=league.lock_offset_minutes,
        timezone=league.timezone,
        first_scored_week=league.first_scored_week,
        last_scored_week=league.last_scored_week,
        # The URL itself is never serialized -- only whether one is configured.
        has_discord_webhook=bool(league.discord_webhook_url),
        your_role=your_role,
    )


def league_detail_out(
    league: League, members: list[LeagueMember], user: User | None
) -> LeagueDetailOut:
    uid = user.id if user else None
    your_role = next((m.role for m in members if m.user_id == uid), None)
    base = league_out(league, your_role)
    return LeagueDetailOut(
        **base.model_dump(),
        members=sorted(
            (member_out(m, uid) for m in members),
            key=lambda m: (not m.has_app_account, m.display_name.lower()),
        ),
    )


async def round_out(
    session: AsyncSession, league: League, rnd: ParlayRound, user: User | None
) -> RoundOut:
    """Everything the league home page needs in one payload."""
    uid = user.id if user else None

    members = {
        m.id: m
        for m in (
            await session.scalars(
                select(LeagueMember).where(LeagueMember.league_id == league.id)
            )
        ).all()
    }
    round_legs = await legs_service.list_legs(session, rnd)

    submitted_member_ids = {leg.member_id for leg in round_legs}
    eligible = [m for m in members.values() if m.user_id is not None]
    awaiting = [m for m in eligible if m.id not in submitted_member_ids]

    your_member = next((m for m in members.values() if m.user_id == uid), None)
    your_member_id = your_member.id if your_member else None
    your_leg = next((leg for leg in round_legs if leg.member_id == your_member_id), None)

    loser_member = members.get(rnd.loser_member_id) if rnd.loser_member_id else None
    status = round_status(rnd)

    return RoundOut(
        id=rnd.id,
        league_id=rnd.league_id,
        season=rnd.season,
        scored_week=rnd.scored_week,
        bet_week=rnd.bet_week,
        status=status,
        opens_at=rnd.opens_at,
        locks_at=rnd.locks_at,
        loser=member_out(loser_member, uid) if loser_member else None,
        loser_points=rnd.loser_points,
        tie_roster_ids=rnd.tie_roster_ids,
        loser_has_app_account=bool(loser_member and loser_member.user_id),
        outcome=rnd.outcome,
        final_odds=rnd.final_odds,
        stake_cents=rnd.stake_cents,
        payout_cents=rnd.payout_cents,
        notes=rnd.notes,
        # Legs are visible to everyone as soon as they land, matching how the
        # spreadsheet worked.
        legs=[leg_out(leg, members.get(leg.member_id), uid) for leg in round_legs],
        awaiting=sorted(
            (member_out(m, uid) for m in awaiting), key=lambda m: m.display_name.lower()
        ),
        submitted_count=len(round_legs),
        eligible_count=len(eligible),
        your_leg=leg_out(your_leg, your_member, uid) if your_leg else None,
        you_can_submit=bool(your_member) and status == "open",
    )
