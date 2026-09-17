"""Outbound notifications: email via Resend, plus an optional Discord/Slack webhook.

Every send is recorded in notifications_log with UNIQUE(round_id, kind, channel, target).
The scheduler is best-effort and may fire twice; the ledger is what guarantees the league
does not get spammed.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.http import get_client
from app.models import League, LeagueMember, NotificationLog, ParlayRound, User, WeekScore
from app.services import email_templates as tpl
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


async def _week_scores(
    session: AsyncSession, league: League, rnd: ParlayRound
) -> list[tuple[str, float]]:
    """Every roster's score for the scored week, lowest first.

    Already cached for the loser calculation, so putting it in the email costs one query
    and answers the question everyone asks anyway: how close was it.
    """
    stmt = (
        select(LeagueMember.display_name, WeekScore.points)
        .join(WeekScore, WeekScore.sleeper_roster_id == LeagueMember.sleeper_roster_id)
        .where(
            LeagueMember.league_id == league.id,
            WeekScore.league_id == league.id,
            WeekScore.season == league.season,
            WeekScore.week == rnd.scored_week,
        )
        .order_by(WeekScore.points.asc())
    )
    return [(row[0], float(row[1])) for row in (await session.execute(stmt)).all()]


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
    missing = [m for m in eligible if m.id not in submitted_ids]
    missing_names = [m.display_name for m in missing]

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
                f"{league.name.strip()}: {loser_name} lost week {rnd.scored_week}"
                f" - submit your leg",
                tpl.round_opened(
                    league_name=league.name,
                    loser_name=loser_name,
                    loser_points=rnd.loser_points,
                    scored_week=rnd.scored_week,
                    bet_week=rnd.bet_week,
                    deadline=_deadline_text(rnd, league),
                    scores=await _week_scores(session, league, rnd),
                    url=league_url,
                ),
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
                f"{league.name.strip()}: your week {rnd.bet_week} leg is still missing",
                tpl.reminder(
                    league_name=league.name,
                    loser_name=loser_name,
                    bet_week=rnd.bet_week,
                    deadline=_deadline_text(rnd, league),
                    missing_names=missing_names,
                    submitted=len(submitted_ids),
                    eligible=len(eligible),
                    url=league_url,
                ),
            )
            sent.append(KIND_REMINDER)

    # 3 and 4. The finished parlay, to the whole league.
    #
    # Everyone contributed a leg, so everyone gets to see what it became -- not just the
    # person paying for it. The payer's copy is framed differently (go and place this)
    # and is the only one carrying the paste-ready block.
    leg_pairs = [(x.raw_text, names.get(x.member_id, "")) for x in round_legs]
    deadline = _deadline_text(rnd, league)

    def _body(is_payer: bool, locked: bool) -> str:
        return tpl.legs_ready(
            league_name=league.name,
            loser_name=loser_name,
            bet_week=rnd.bet_week,
            deadline=deadline,
            legs=leg_pairs,
            url=league_url,
            locked=locked,
            missing_names=missing_names if locked else [],
            is_payer=is_payer,
        )

    everyone_in = bool(eligible) and len(submitted_ids) == len(eligible)

    if status == STATUS_OPEN and everyone_in:
        for person in recipients:
            if await _already_sent(session, rnd.id, KIND_ALL_LEGS_IN, "email", person.email):
                continue
            if not await _record(session, rnd.id, KIND_ALL_LEGS_IN, "email", person.email):
                continue
            payer = loser_email is not None and person.email == loser_email
            subject = (
                f"{league.name.strip()}: all {len(round_legs)} legs are in - time to place it"
                if payer
                else f"{league.name.strip()}: the week {rnd.bet_week} parlay is set"
                f" - {len(round_legs)} legs"
            )
            await send_email(person.email, subject, _body(payer, locked=False))
            sent.append(KIND_ALL_LEGS_IN)

        if league.discord_webhook_url and not await _already_sent(
            session, rnd.id, KIND_ALL_LEGS_IN, "discord", "webhook"
        ):
            if await _record(session, rnd.id, KIND_ALL_LEGS_IN, "discord", "webhook"):
                lines = "\n".join(
                    f"{i}. {text} - {who}" for i, (text, who) in enumerate(leg_pairs, 1)
                )
                await send_webhook(
                    league.discord_webhook_url,
                    f"**Week {rnd.bet_week} parlay is set** - all {len(round_legs)} legs in, "
                    f"funded by {loser_name}.\n{lines}\n{league_url}",
                )
                sent.append(KIND_ALL_LEGS_IN)

    # 4. Locked -- the final list, to anyone the early send did not already reach.
    if status == STATUS_LOCKED:
        for person in recipients:
            # Skip people who already saw this exact list when the board filled early;
            # otherwise a league that submits on time gets the same parlay twice.
            if await _already_sent(session, rnd.id, KIND_ALL_LEGS_IN, "email", person.email):
                continue
            if await _already_sent(session, rnd.id, KIND_LOCKED, "email", person.email):
                continue
            if not await _record(session, rnd.id, KIND_LOCKED, "email", person.email):
                continue
            payer = loser_email is not None and person.email == loser_email
            await send_email(
                person.email,
                f"{league.name.strip()}: week {rnd.bet_week} parlay is locked"
                f" - {len(round_legs)} legs",
                _body(payer, locked=True),
            )
            sent.append(KIND_LOCKED)

    return sent


# ---------------------------------------------------------------- settling the parlay

KIND_RESOLVED = "resolved"

_RESOLVED_WORD = {"won": "cashed", "lost": "busted", "void": "voided"}
_DISCORD_MARK = {"hit": "✅", "miss": "❌", "push": "➖", "void": "➖"}


def resolution_kind(outcome: str) -> str:
    """Ledger kind for an outcome.

    Keyed on the outcome rather than a single "resolved", so a correction is announced
    too: a parlay wrongly settled as busted and later corrected to cashed tells the league
    both times, while each outcome is still only ever announced once.
    """
    return f"{KIND_RESOLVED}_{outcome}"


async def notify_resolution(
    session: AsyncSession, league: League, rnd: ParlayRound, app_url: str
) -> list[str]:
    """Tell the whole league the parlay settled, and which leg decided it."""
    if rnd.outcome not in _RESOLVED_WORD:
        return []

    kind = resolution_kind(rnd.outcome)
    sent: list[str] = []
    league_url = f"{app_url.rstrip('/')}/leagues/{league.id}"

    members = (
        await session.scalars(select(LeagueMember).where(LeagueMember.league_id == league.id))
    ).all()
    names = {m.id: m.display_name for m in members}
    loser_name = names.get(rnd.loser_member_id, "Nobody") if rnd.loser_member_id else "Nobody"

    round_legs = await legs_service.list_legs(session, rnd)
    rows = [
        (leg.raw_text, names.get(leg.member_id, ""), leg.result, leg.grade_detail)
        for leg in round_legs
    ]

    subject = f"{league.name.strip()}: week {rnd.bet_week} parlay {_RESOLVED_WORD[rnd.outcome]}"
    html = tpl.parlay_resolved(
        league_name=league.name,
        loser_name=loser_name,
        bet_week=rnd.bet_week,
        outcome=rnd.outcome,
        legs=rows,
        url=league_url,
    )

    for person in await _recipients(session, league):
        if await _already_sent(session, rnd.id, kind, "email", person.email):
            continue
        if not await _record(session, rnd.id, kind, "email", person.email):
            continue
        await send_email(person.email, subject, html)
        sent.append(kind)

    if league.discord_webhook_url and not await _already_sent(
        session, rnd.id, kind, "discord", "webhook"
    ):
        if await _record(session, rnd.id, kind, "discord", "webhook"):
            message = _discord_resolution(rnd, loser_name, rows, league_url)
            await send_webhook(league.discord_webhook_url, message)
            sent.append(kind)

    return sent


def _discord_resolution(
    rnd: ParlayRound,
    loser_name: str,
    rows: list[tuple[str, str, str, str | None]],
    url: str,
) -> str:
    week = rnd.bet_week
    if rnd.outcome == "lost":
        text, who, _, detail = next(r for r in rows if r[2] == "miss")
        why = f" ({detail})" if detail else ""
        headline = f"**Week {week} parlay busted** - sunk by {who}'s {text}{why}."
    elif rnd.outcome == "won":
        headline = f"**Week {week} parlay cashed!** Every leg came in. Funded by {loser_name}."
    else:
        headline = f"**Week {week} parlay voided** - every leg pushed or was voided."
    lines = "\n".join(
        f"{_DISCORD_MARK.get(result, '⏳')} {text} - {who}" for text, who, result, _ in rows
    )
    return f"{headline}\n{lines}\n{url}"
