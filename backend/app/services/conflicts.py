"""Which legs cannot share a parlay.

A week's parlay is one bet slip: every leg multiplies into the same payout. Two legs that
cannot both win make the slip unwinnable before a ball is thrown, and two legs on the same
thing spend two of the league's slots on one opinion. Both are refused at submission, while
the person is still looking at the box they typed into.

What counts as "the same thing" is deliberately coarse. Saquon over 50 and Saquon over 30
do not contradict each other -- the second is nearly free if the first lands -- but they are
one opinion bet twice, which is the thing the league wanted stopped.

Refusing needs a reading, so a leg is read before it is accepted rather than just after.
When that reading cannot be had the leg is taken anyway: see `find`.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.espn import WeekSchedule
from app.models import LeagueMember, Leg, ParlayRound
from app.services import grading
from app.services import legs as legs_service

# Why a key is exclusive, written to be read by whoever just got turned down.
_RULES: dict[str, str] = {
    "player": "The league takes one bet per player per stat.",
    "winner": "The league takes one bet on who wins a game -- either side of it counts.",
    "game_total": "The league takes one bet on a game's total.",
    "team_total": "The league takes one bet on a team's total.",
}


def _game(team: str, schedule: WeekSchedule | None) -> str:
    """The game a team is in, so both sides of one game share a key.

    Falls back to the team itself when the schedule cannot say -- a bye, a misread
    abbreviation, or ESPN being down. That still catches the literal duplicate and lets
    the opposite side through, which is the safe way to be wrong.
    """
    event = schedule.event_for_team(team) if schedule else None
    return event.event_id if event else team


def key(parsed: dict | None, schedule: WeekSchedule | None) -> tuple[str, str] | None:
    """What this leg occupies. Two legs with the same key cannot both be in the parlay.

    None means "occupies nothing we can police" -- unread, unreadable, or a market with no
    subject to collide on. Those are always allowed through.
    """
    if not parsed or not parsed.get("understood"):
        return None
    market = parsed.get("market")

    if market in grading.PLAYER_MARKETS:
        subject = parsed.get("subject")
        if not subject:
            return None
        # The line and the direction are left out on purpose: over 50 and under 50 are a
        # contradiction, over 50 and over 30 are a repetition, and neither belongs on one
        # slip. Different stats for the same player are fine -- Saquon's yards and Saquon's
        # touchdowns are genuinely different bets.
        return ("player", f"{grading.name_key(subject)} {market}")

    team = parsed.get("team")
    if not team:
        return None
    if market in ("moneyline", "spread"):
        # One key for the whole game. A spread and a moneyline on the same side are the
        # same opinion; the two sides are opposite ones. The parlay gains nothing either way.
        return ("winner", _game(team, schedule))
    if market == "game_total":
        return ("game_total", _game(team, schedule))
    if market == "team_total":
        # Per team rather than per game: both teams going over is not a contradiction.
        return ("team_total", team)
    return None


@dataclass(frozen=True)
class Clash:
    """An existing leg that a new one cannot sit beside."""

    leg: Leg
    rule: str

    def message(self, who: str) -> str:
        return f'{who} already has "{self.leg.raw_text}". {self.rule}'


def find(parsed: dict | None, schedule: WeekSchedule | None, others: list[Leg]) -> Clash | None:
    """The first leg in `others` that rules this one out, if any.

    A leg nobody has read yet has no key, so it cannot be clashed against. That is the
    intended failure: letting a duplicate through costs the league an argument, while
    refusing a legal bet because the parser was down costs someone their week.
    """
    mine = key(parsed, schedule)
    if mine is None:
        return None
    for other in others:
        if key(other.parsed, schedule) == mine:
            return Clash(other, _RULES[mine[0]])
    return None


async def refusal(
    session: AsyncSession,
    rnd: ParlayRound,
    member: LeagueMember,
    parsed: dict | None,
    schedule: WeekSchedule | None,
) -> str | None:
    """Why this member cannot submit this leg, or None if they can.

    Their own leg is excluded: everyone gets exactly one, and submitting again replaces it.
    """
    others = [
        leg for leg in await legs_service.list_legs(session, rnd) if leg.member_id != member.id
    ]
    clash = find(parsed, schedule, others)
    if clash is None:
        return None
    owner = await session.get(LeagueMember, clash.leg.member_id)
    return clash.message(owner.display_name if owner else "Someone else")
