"""Leg submission.

`raw_text` is written exactly as typed and is the permanent source of truth. The parsing
pass writes to `parsed` only, so a bad reading can never destroy what someone actually meant
to bet.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LeagueMember, Leg, ParlayRound
from app.services.rounds import STATUS_LOCKED, STATUS_UPCOMING, round_status

log = logging.getLogger(__name__)


async def list_legs(session: AsyncSession, rnd: ParlayRound) -> list[Leg]:
    stmt = (
        select(Leg)
        .where(Leg.round_id == rnd.id)
        .order_by(Leg.created_at)
    )
    return list((await session.scalars(stmt)).all())


async def get_member_leg(
    session: AsyncSession, rnd: ParlayRound, member: LeagueMember
) -> Leg | None:
    return await session.scalar(
        select(Leg).where(Leg.round_id == rnd.id, Leg.member_id == member.id)
    )


def assert_submittable(rnd: ParlayRound) -> None:
    state = round_status(rnd)
    if state == STATUS_LOCKED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Submissions for this week are locked -- kickoff is too close.",
        )
    if state == STATUS_UPCOMING:
        raise HTTPException(status.HTTP_409_CONFLICT, "This round has not opened yet.")


async def upsert_leg(
    session: AsyncSession, rnd: ParlayRound, member: LeagueMember, raw_text: str
) -> Leg:
    """Create or replace this member's single leg. Editable right up until lock."""
    assert_submittable(rnd)

    text = raw_text.strip()
    if len(text) < 2:
        # Literal 422 -- Starlette renamed its constant and we support both versions.
        raise HTTPException(422, "Your leg looks empty.")

    leg = await get_member_leg(session, rnd, member)
    if leg is None:
        leg = Leg(round_id=rnd.id, member_id=member.id, raw_text=text)
        session.add(leg)
    else:
        if leg.raw_text != text:
            leg.raw_text = text
            # A different bet: everything read or settled from the old text goes, including
            # a line the payer recorded, which belonged to the bet that no longer exists.
            leg.parsed = None
            leg.result = "pending"
            leg.payer_line = None
            leg.grade_detail = None
            leg.graded_by = None
            leg.graded_at = None
            leg.espn_event_id = None

    try:
        await session.commit()
    except IntegrityError:
        # UNIQUE(round_id, member_id) tripped by a concurrent double-submit.
        await session.rollback()
        existing = await get_member_leg(session, rnd, member)
        if existing is None:
            raise
        return existing

    await session.refresh(leg)
    return leg


async def delete_leg(session: AsyncSession, rnd: ParlayRound, member: LeagueMember) -> bool:
    assert_submittable(rnd)
    leg = await get_member_leg(session, rnd, member)
    if leg is None:
        return False
    await session.delete(leg)
    await session.commit()
    return True


async def eligible_members(session: AsyncSession, rnd: ParlayRound) -> list[LeagueMember]:
    """Members who can actually submit -- i.e. rosters claimed by an app account."""
    stmt = select(LeagueMember).where(
        LeagueMember.league_id == rnd.league_id, LeagueMember.user_id.is_not(None)
    )
    return list((await session.scalars(stmt)).all())
