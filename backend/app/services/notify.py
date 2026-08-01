"""Outbound notifications: email via Resend, plus an optional Discord/Slack webhook.

Every send is recorded in notifications_log with UNIQUE(round_id, kind, channel, target).
The scheduler is best-effort and may fire twice; the ledger is what guarantees the league
does not get spammed.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.http import get_client
from app.models import League, LeagueMember, NotificationLog, ParlayRound, User
from app.services import legs as legs_service
from app.services.rounds import STATUS_LOCKED, STATUS_OPEN, round_status

log = logging.getLogger(__name__)

KIND_ROUND_OPENED = "round_opened"
KIND_REMINDER = "reminder"
KIND_ALL_LEGS_IN = "all_legs_in"
KIND_LOCKED = "locked"

# Nudge non-submitters once, this close to the deadline.
REMINDER_WINDOW_SECONDS = 24 * 3600


@dataclass
class Recipient:
    email: str
    name: str


async def _already_sent(
    session: AsyncSession, round_id, kind: str, channel: str, target: str
) -> bool:
    existing = await session.scalar(
        select(NotificationLog).where(
            NotificationLog.round_id == round_id,
            NotificationLog.kind == kind,
            NotificationLog.channel == channel,
            NotificationLog.target == target,
        )
    )
    return existing is not None


async def _record(
    session: AsyncSession, round_id, kind: str, channel: str, target: str
) -> bool:
    """Claim the right to send. Returns False if someone already did."""
    session.add(
        NotificationLog(
            round_id=round_id, kind=kind, channel=channel, target=target, sent_at=datetime.now(UTC)
        )
    )
    try:
        await session.commit()
        return True
    except IntegrityError:
        # Lost the race against a concurrent tick.
        await session.rollback()
        return False


async def send_email(to: str, subject: str, html: str) -> bool:
    if not settings.resend_api_key:
        log.info("RESEND_API_KEY unset; would have emailed %s: %s", to, subject)
        return False

    client = get_client()
    response = await client.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={"from": settings.email_from, "to": [to], "subject": subject, "html": html},
    )
    if response.status_code >= 400:
        log.error("Resend rejected email to %s: %s %s", to, response.status_code, response.text)
        return False
    return True


async def send_webhook(url: str, content: str) -> bool:
    client = get_client()
    response = await client.post(url, json={"content": content})
    if response.status_code >= 400:
        log.error("Webhook failed: %s %s", response.status_code, response.text)
        return False
    return True


async def _recipients(session: AsyncSession, league: League) -> list[Recipient]:
    stmt = (
        select(User.email, LeagueMember.display_name)
        .join(LeagueMember, LeagueMember.user_id == User.id)
        .where(LeagueMember.league_id == league.id)
    )
    return [Recipient(email=row[0], name=row[1]) for row in (await session.execute(stmt)).all()]


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _deadline_text(rnd: ParlayRound, league: League) -> str:
    """Render the deadline in the league's own timezone.

    Uses only portable strftime directives -- the %-d / %-I forms are glibc-only and
    raise on Windows.
    """
    locks = _as_utc(rnd.locks_at)
    try:
        locks = locks.astimezone(ZoneInfo(league.timezone))
        label = locks.strftime("%Z")
    except (ZoneInfoNotFoundError, ValueError):
        label = "UTC"
    return f"{locks.strftime('%a %b %d, %I:%M %p').replace(' 0', ' ')} {label}"


def _round_opened_body(league: League, rnd: ParlayRound, loser_name: str, url: str) -> str:
    points = f"{rnd.loser_points:.2f}" if rnd.loser_points is not None else "?"
    return f"""
    <p><strong>{escape(loser_name)}</strong> was low scorer in week {rnd.scored_week}
    ({points} pts) and is funding this week's parlay.</p>
    <p>Submit your leg for <strong>week {rnd.bet_week}</strong> before
    {_deadline_text(rnd, league)}.</p>
    <p><a href="{url}">Submit your leg</a></p>
    """


async def notify_round(
    session: AsyncSession, league: League, rnd: ParlayRound, app_url: str
) -> list[str]:
    """Send whatever this round is due. Returns the kinds actually dispatched."""
    sent: list[str] = []
    status = round_status(rnd)
    league_url = f"{app_url.rstrip('/')}/leagues/{league.id}"

    loser_name = "Nobody yet"
    loser_email: str | None = None
    if rnd.loser_member_id:
        member = await session.get(LeagueMember, rnd.loser_member_id)
        if member:
            loser_name = member.display_name
            if member.user_id:
                user = await session.get(User, member.user_id)
                loser_email = user.email if user else None

    recipients = await _recipients(session, league)
    round_legs = await legs_service.list_legs(session, rnd)
    eligible = await legs_service.eligible_members(session, rnd)
    submitted_ids = {leg.member_id for leg in round_legs}

    # Names are resolved up front: touching leg.member lazily would trigger IO outside
    # the async greenlet and raise MissingGreenlet.
    all_members = (
        await session.scalars(select(LeagueMember).where(LeagueMember.league_id == league.id))
    ).all()
    names = {m.id: m.display_name for m in all_members}

    # 1. Round opened -- tell everyone who lost and that legs are due.
    if status == STATUS_OPEN and rnd.loser_member_id:
        for person in recipients:
            if await _already_sent(session, rnd.id, KIND_ROUND_OPENED, "email", person.email):
                continue
            if not await _record(session, rnd.id, KIND_ROUND_OPENED, "email", person.email):
                continue
            await send_email(
                person.email,
                f"{league.name}: {loser_name} lost week {rnd.scored_week} - submit your leg",
                _round_opened_body(league, rnd, loser_name, league_url),
            )
            sent.append(KIND_ROUND_OPENED)

        if league.discord_webhook_url and not await _already_sent(
            session, rnd.id, KIND_ROUND_OPENED, "discord", "webhook"
        ):
            if await _record(session, rnd.id, KIND_ROUND_OPENED, "discord", "webhook"):
                await send_webhook(
                    league.discord_webhook_url,
                    f"**{loser_name}** was low scorer in week {rnd.scored_week} "
                    f"({rnd.loser_points:.2f} pts) and funds this week's parlay.\n"
                    f"Submit your week {rnd.bet_week} leg: {league_url}",
                )
                sent.append(KIND_ROUND_OPENED)

    # 2. Reminder -- only the stragglers, only inside the final day.
    remaining = (
        rnd.locks_at if rnd.locks_at.tzinfo else rnd.locks_at.replace(tzinfo=UTC)
    ) - datetime.now(UTC)
    if status == STATUS_OPEN and 0 < remaining.total_seconds() <= REMINDER_WINDOW_SECONDS:
        missing = [m for m in eligible if m.id not in submitted_ids]
        for member in missing:
            if not member.user_id:
                continue
            user = await session.get(User, member.user_id)
            if user is None:
                continue
            if await _already_sent(session, rnd.id, KIND_REMINDER, "email", user.email):
                continue
            if not await _record(session, rnd.id, KIND_REMINDER, "email", user.email):
                continue
            await send_email(
                user.email,
                f"{league.name}: your week {rnd.bet_week} leg is still missing",
                f"<p>Legs lock at {_deadline_text(rnd, league)}."
                f' <a href="{league_url}">Submit yours</a>.</p>',
            )
            sent.append(KIND_REMINDER)

    # 3. All legs in -- the loser can go place the bet without waiting for the deadline.
    if status == STATUS_OPEN and eligible and len(submitted_ids) == len(eligible) and loser_email:
        if not await _already_sent(session, rnd.id, KIND_ALL_LEGS_IN, "email", loser_email):
            if await _record(session, rnd.id, KIND_ALL_LEGS_IN, "email", loser_email):
                await send_email(
                    loser_email,
                    f"{league.name}: all {len(round_legs)} legs are in - time to place it",
                    _legs_html(round_legs, names, league_url),
                )
                sent.append(KIND_ALL_LEGS_IN)

    # 4. Locked -- final list, whether or not everyone submitted.
    if status == STATUS_LOCKED and loser_email:
        if not await _already_sent(session, rnd.id, KIND_LOCKED, "email", loser_email):
            if await _record(session, rnd.id, KIND_LOCKED, "email", loser_email):
                await send_email(
                    loser_email,
                    f"{league.name}: week {rnd.bet_week} parlay is locked - {len(round_legs)} legs",
                    _legs_html(round_legs, names, league_url),
                )
                sent.append(KIND_LOCKED)

    return sent


def _legs_html(round_legs, names: dict, url: str) -> str:
    items = "".join(
        f"<li>{escape(leg.raw_text)} "
        f"<em style='color:#888'>&mdash; {escape(names.get(leg.member_id, ''))}</em></li>"
        for leg in round_legs
    )
    return f"<ol>{items}</ol><p><a href='{url}'>Open the board</a></p>"
