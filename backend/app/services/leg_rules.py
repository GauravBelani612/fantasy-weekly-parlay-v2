"""Why a leg can be refused.

Two reasons so far, both decided at submission while the person is still looking at the box
they typed into: the leg repeats or contradicts one already in, or it rides on a game that
starts before the league's betting window opens.

A week's parlay is one bet slip: every leg multiplies into the same payout. Two legs that
cannot both land make the slip unwinnable before a ball is thrown. Two legs on one opinion
are the subtler problem -- the slip collects odds twice for risk it only took once, which
is what a sportsbook means by correlated, and why it would decline to write the ticket at
all. Neither is a house rule this league invented; both are refused at submission, while
the person is still looking at the box they typed into.

What counts as "the same thing" is therefore coarse on purpose. Saquon over 50 and Saquon
over 30 do not contradict each other, but the second is all but implied by the first, so it
is paid for without ever being at risk.

Refusing needs a reading, so a leg is read before it is accepted rather than just after.
When that reading cannot be had the leg is taken anyway: see `find`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.espn import NflEvent, WeekSchedule
from app.models import LeagueMember, Leg, ParlayRound
from app.services import grading
from app.services import legs as legs_service

# Why a key is exclusive, written to be read by whoever just got turned down. Phrased as
# what a parlay allows rather than what the league prefers, because that is what it is.
_RULES: dict[str, str] = {
    "player": "A parlay takes one bet per player per stat.",
    "winner": "A parlay takes one bet on a game's result -- moneyline or spread, either side.",
    "game_total": "A parlay takes one bet on a game's total.",
    "team_total": "A parlay takes one bet on a team's total.",
}


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; normalize before comparing."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _event_for(parsed: dict, schedule: WeekSchedule | None) -> NflEvent | None:
    """The game this leg rides on, whether it names a team or a player on one.

    A player leg carries the team its reading was corrected to, so this is only as good as
    the roster lookup that set it -- which is why that runs before any of this.
    """
    team = parsed.get("team")
    return schedule.event_for_team(team) if team and schedule else None


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
        # One key for the whole game, covering both sides and both markets.
        #
        # Opposite sides cannot both land, so that slip is dead before kickoff. The same
        # side is the interesting case: a moneyline is the -0.5 spread in all but name, and
        # KC -3.5 already implies it. The wider line carries the entire bet while the
        # moneyline leg collects odds without ever being at risk -- correlated, and not a
        # ticket any book would write.
        return ("winner", _game(team, schedule))
    if market == "game_total":
        return ("game_total", _game(team, schedule))
    if market == "team_total":
        # Per team rather than per game: both teams going over is not a contradiction.
        return ("team_total", team)
    return None


def too_early(
    parsed: dict | None, schedule: WeekSchedule | None, window_opens_at: datetime | None
) -> str | None:
    """Why this leg starts too soon for the league's window, or None if it does not.

    A league that bets Sunday onward is saying the parlay is a Sunday thing. A Thursday leg
    is settled before most of the league has watched a snap, and can leave the whole slip
    dead before the day they actually care about starts.

    Unknown means allowed, as everywhere else here: no window set, nothing read, or a game
    the schedule cannot place (a bye, a misread abbreviation) all pass through.
    """
    if window_opens_at is None or not parsed or not parsed.get("understood"):
        return None
    event = _event_for(parsed, schedule)
    if event is None:
        return None
    if _as_utc(event.kickoff_at) >= _as_utc(window_opens_at):
        return None
    return (
        f"{event.name} kicks off before Sunday football starts. This league bets from the "
        "first Sunday game on, so pick a game starting then or later."
    )


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

    The window is checked first: a leg outside it is wrong on its own terms, so saying so is
    more use than naming whoever happens to also hold it.
    """
    if early := too_early(parsed, schedule, rnd.window_opens_at):
        return early

    # Their own leg is excluded: everyone gets one, and submitting again replaces it.
    others = [
        leg for leg in await legs_service.list_legs(session, rnd) if leg.member_id != member.id
    ]
    clash = find(parsed, schedule, others)
    if clash is None:
        return None
    owner = await session.get(LeagueMember, clash.leg.member_id)
    return clash.message(owner.display_name if owner else "Someone else")
