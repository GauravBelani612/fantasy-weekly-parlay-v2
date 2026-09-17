"""Grading a parsed leg against a finished game.

No database access here. Box scores arrive through an injected loader, so every rule can
be exercised against a handmade game and any disputed result reproduced exactly. That
matters more than usual: this is the code a league argues with.

The rules follow how sportsbooks settle, with one league rule on top: there are no pushes.
Every leg is a hit or a miss, and the only way a leg drops out is its player not playing.

- "N+" is inclusive: three receptions settles "3+ receptions" as a hit.
- Over and under are strict. "Over 70" landing on exactly 70 did not go over, so it is a
  miss -- not the push a sportsbook would call it. The same goes for a spread covered by
  exactly the number and a moneyline that ends tied.
- Anytime touchdowns count rushing, receiving and return scores -- never a quarterback's
  passing touchdowns.
- A player who did not play voids the leg rather than losing it, but only when ESPN
  ruled them out. A player merely missing from a box score is left for a person, because
  that also describes a misread name, and guessing would void a real miss.
"""

import difflib
import re
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from app.integrations.espn import GameSummary, PlayerLine, WeekSchedule

PENDING = "pending"
HIT = "hit"
MISS = "miss"
VOID = "void"
NEEDS_LINE = "needs_line"
UNRESOLVED = "unresolved"

TERMINAL = frozenset({HIT, MISS, VOID})
# What the payer or commissioner may set by hand. PENDING hands the leg back to the grader.
MANUAL_RESULTS = frozenset({HIT, MISS, VOID, PENDING})

# Market -> the box-score stats that sum to it.
PLAYER_MARKETS: dict[str, tuple[str, ...]] = {
    "touchdowns": ("rushing_touchdowns", "receiving_touchdowns", "return_touchdowns"),
    "passing_yards": ("passing_yards",),
    "passing_touchdowns": ("passing_touchdowns",),
    "interceptions_thrown": ("interceptions_thrown",),
    "completions": ("completions",),
    "passing_attempts": ("passing_attempts",),
    "rushing_yards": ("rushing_yards",),
    "rushing_attempts": ("rushing_attempts",),
    "rushing_touchdowns": ("rushing_touchdowns",),
    "receptions": ("receptions",),
    "receiving_yards": ("receiving_yards",),
    "receiving_touchdowns": ("receiving_touchdowns",),
    "rushing_and_receiving_yards": ("rushing_yards", "receiving_yards"),
}
TEAM_MARKETS = ("moneyline", "spread", "game_total", "team_total")

_LABELS = {
    "touchdowns": ("TD", "TDs"),
    "passing_yards": ("passing yd", "passing yds"),
    "passing_touchdowns": ("passing TD", "passing TDs"),
    "interceptions_thrown": ("INT", "INTs"),
    "completions": ("completion", "completions"),
    "passing_attempts": ("pass attempt", "pass attempts"),
    "rushing_yards": ("rushing yd", "rushing yds"),
    "rushing_attempts": ("carry", "carries"),
    "rushing_touchdowns": ("rushing TD", "rushing TDs"),
    "receptions": ("catch", "catches"),
    "receiving_yards": ("receiving yd", "receiving yds"),
    "receiving_touchdowns": ("receiving TD", "receiving TDs"),
    "rushing_and_receiving_yards": ("rush+rec yd", "rush+rec yds"),
    "moneyline": ("moneyline", "moneyline"),
    "spread": ("spread", "spread"),
    "game_total": ("game total", "game total"),
    "team_total": ("team total", "team total"),
}

_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


@dataclass(frozen=True)
class Grade:
    result: str
    detail: str
    event_id: str | None = None
    # When the game starts, for a leg still waiting on one. Passed through as a timestamp
    # rather than formatted into `detail`, so each reader sees their own clock.
    kickoff_at: datetime | None = None


SummaryLoader = Callable[[str], Awaitable[GameSummary | None]]


# ------------------------------------------------------------------------ helpers


def _label(market: str, value: float) -> str:
    one, many = _LABELS.get(market, (market, market))
    return one if value == 1 else many


def _fmt(value: float | None) -> str:
    return "?" if value is None else f"{value:g}"


def name_key(name: str) -> str:
    """Normalise a player name for matching: "Ja'Marr Chase" == "jamarr chase".

    Hyphens become spaces and suffixes are dropped, so "Amon-Ra St. Brown" and
    "Brian Parker II" line up however someone typed them.
    """
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[-_]", " ", text.lower())
    text = re.sub(r"[^a-z\s]", "", text)
    return " ".join(p for p in text.split() if p not in _SUFFIXES)


@dataclass(frozen=True)
class PlayerMatch:
    player: PlayerLine | None
    ambiguous: bool = False


def find_player(players: list[PlayerLine], name: str, *, fuzzy: bool = True) -> PlayerMatch:
    """Find one player by name. Never guesses between two candidates."""
    want = name_key(name)
    if not want:
        return PlayerMatch(None)
    compact = want.replace(" ", "")

    exact = [
        p
        for p in players
        if (k := name_key(p.name)) == want or k.replace(" ", "") == compact
    ]
    if len(exact) == 1:
        return PlayerMatch(exact[0])
    if len(exact) > 1:
        return PlayerMatch(None, ambiguous=True)
    if not fuzzy:
        return PlayerMatch(None)

    # Same surname and first initial: "D. Henry" or a dropped middle name.
    parts = want.split()
    if len(parts) >= 2:
        loose = [
            p for p in players
            if (k := name_key(p.name).split())
            and k[-1] == parts[-1] and k[0][:1] == parts[0][:1]
        ]
        if len(loose) == 1:
            return PlayerMatch(loose[0])
        if len(loose) > 1:
            return PlayerMatch(None, ambiguous=True)

    # Last resort for spelling. The cutoff is deliberately high: a wrong match here grades
    # somebody else's stat line, which is worse than asking a person.
    keys = {name_key(p.name): p for p in players}
    close = difflib.get_close_matches(want, list(keys), n=2, cutoff=0.88)
    if len(close) == 1:
        return PlayerMatch(keys[close[0]])
    if len(close) > 1:
        return PlayerMatch(None, ambiguous=True)
    return PlayerMatch(None)


def _ruled_out(summary: GameSummary, name: str) -> str | None:
    want = name_key(name)
    return next((s for n, s in summary.ruled_out.items() if name_key(n) == want), None)


def _compare(value: float, direction: str | None, line: float) -> str | None:
    if direction == "at_least":
        return HIT if value >= line else MISS
    # Strict, by league rule: exactly on the line is not over and not under.
    if direction == "over":
        return HIT if value > line else MISS
    if direction == "under":
        return HIT if value < line else MISS
    return None


def _describe(direction: str | None, line: float | None) -> str:
    if direction == "at_least":
        return f"needed {_fmt(line)}+"
    if direction in ("over", "under"):
        return f"line {direction} {_fmt(line)}"
    return ""


def needs_line(parsed: dict | None, payer_line: float | None) -> bool:
    """True when the bet cannot be settled without a number nobody has recorded."""
    if not parsed or not parsed.get("understood"):
        return False
    if parsed.get("market") == "moneyline":
        return False
    return payer_line is None and parsed.get("line") is None


def read_as(parsed: dict | None, payer_line: float | None = None) -> str | None:
    """How the leg was understood, in a form a league member can sanity-check."""
    if not parsed:
        return None
    if not parsed.get("understood"):
        return "Couldn't read this leg"

    market = parsed.get("market", "")
    line = payer_line if payer_line is not None else parsed.get("line")
    direction = parsed.get("direction")
    team = parsed.get("team")
    subject = parsed.get("subject")
    line_text = "—" if line is None else _fmt(line)

    if market == "moneyline":
        return f"{team} · moneyline"
    if market == "spread":
        return f"{team} · spread {'—' if line is None else f'{line:+g}'}"
    if market == "game_total":
        return f"{team} game total · {direction or ''} {line_text}".replace("  ", " ")
    if market == "team_total":
        return f"{team} team total · {direction or ''} {line_text}".replace("  ", " ")

    who = f"{subject} ({team})" if team else (subject or "?")
    if market == "touchdowns" and direction == "at_least" and line == 1:
        return f"{who} · anytime TD"
    many = _LABELS.get(market, (market, market))[1]
    if direction == "at_least":
        return f"{who} · {line_text}+ {many}"
    return f"{who} · {many} {direction or ''} {line_text}".replace("  ", " ")


def resolve_outcome(results: list[str]) -> str:
    """Settle the parlay from its legs, the way a sportsbook would.

    One miss loses it immediately, even with games still to play. A voided leg -- a player
    who didn't play -- drops out rather than sinking it; if every leg dropped out, it is void.
    """
    if not results:
        return PENDING
    if MISS in results:
        return "lost"
    if any(r not in TERMINAL for r in results):
        return PENDING
    if all(r == VOID for r in results):
        return "void"
    return "won"


# ------------------------------------------------------------------------ grading


def _evaluate_player(parsed: dict, line: float, player: PlayerLine, event_id: str) -> Grade:
    market = parsed["market"]
    value = sum(player.stat(k) for k in PLAYER_MARKETS[market])
    direction = parsed.get("direction")
    result = _compare(value, direction, line)
    if result is None:
        return Grade(UNRESOLVED, "No over, under or minimum to grade against", event_id)
    detail = f"{player.name}: {_fmt(value)} {_label(market, value)}, {_describe(direction, line)}"
    return Grade(result, detail, event_id)


async def _grade_team(
    parsed: dict, line: float | None, schedule: WeekSchedule, load: SummaryLoader
) -> Grade:
    market = parsed["market"]
    team = parsed.get("team")
    if not team:
        return Grade(UNRESOLVED, "No team named")

    event = schedule.event_for_team(team)
    if event is None:
        return Grade(UNRESOLVED, f"{team} don't play in week {schedule.week}")
    if not event.is_final:
        return Grade(PENDING, f"Waiting on {event.name}", event.event_id, event.kickoff_at)

    summary = await load(event.event_id)
    if summary is None or not summary.is_final:
        return Grade(PENDING, f"Waiting on {event.name}", event.event_id, event.kickoff_at)

    opponent = summary.opponent(team)
    ours, theirs = summary.scores.get(team), summary.scores.get(opponent or "")
    if ours is None or theirs is None:
        return Grade(UNRESOLVED, "Final score unavailable", event.event_id)
    score = f"{team} {ours}, {opponent} {theirs}"

    if market == "moneyline":
        # A tie did not win.
        result = HIT if ours > theirs else MISS
        return Grade(result, score, event.event_id)

    if market == "spread":
        margin = ours + line - theirs
        # Covering by exactly the number is not covering.
        result = HIT if margin > 0 else MISS
        return Grade(result, f"{score}, {team} {line:+g}", event.event_id)

    direction = parsed.get("direction")
    value = ours + theirs if market == "game_total" else ours
    result = _compare(value, direction, line)
    if result is None or direction == "at_least":
        return Grade(UNRESOLVED, "Totals need an over or under", event.event_id)
    which = "total" if market == "game_total" else f"{team} scored"
    detail = f"{score} ({which} {value}), line {direction} {_fmt(line)}"
    return Grade(result, detail, event.event_id)


async def _grade_player(
    parsed: dict, line: float, schedule: WeekSchedule, load: SummaryLoader
) -> Grade:
    subject = parsed.get("subject") or ""
    team = parsed.get("team")
    if not subject:
        return Grade(UNRESOLVED, "No player named")

    event = schedule.event_for_team(team) if team else None

    # The named team is playing: look only in that game. Widening the search when a
    # player is absent is how "Josh Allen" the Jaguars linebacker ends up grading Josh
    # Allen the Bills quarterback's passing line.
    if event is not None:
        if not event.is_final:
            return Grade(PENDING, f"Waiting on {event.name}", event.event_id, event.kickoff_at)
        summary = await load(event.event_id)
        if summary is None or not summary.is_final:
            return Grade(PENDING, f"Waiting on {event.name}", event.event_id, event.kickoff_at)
        match = find_player(summary.players, subject)
        if match.player:
            return _evaluate_player(parsed, line, match.player, event.event_id)
        if match.ambiguous:
            return Grade(UNRESOLVED, f"More than one player matches {subject}", event.event_id)
        if status := _ruled_out(summary, subject):
            return Grade(VOID, f"{subject} was ruled out ({status})", event.event_id)
        return Grade(
            UNRESOLVED,
            f"{subject} isn't in the {event.name} box score -- didn't play, or the name "
            "didn't match",
            event.event_id,
        )

    # No team, or a team that isn't playing (a misread, or a player who has since
    # moved). Search every finished game, and only accept a single clear match -- with
    # an exact name when the team was wrong, since that is already a sign of a misread.
    matches: list[tuple[str, PlayerLine]] = []
    ruled_out: list[tuple[str, str]] = []
    ambiguous = False
    for ev in schedule.events:
        if not ev.is_final:
            continue
        summary = await load(ev.event_id)
        if summary is None:
            continue
        match = find_player(summary.players, subject, fuzzy=team is None)
        ambiguous = ambiguous or match.ambiguous
        if match.player:
            matches.append((ev.event_id, match.player))
        elif status := _ruled_out(summary, subject):
            # Not settled yet: a same-named player may still turn up having played.
            ruled_out.append((ev.event_id, status))

    if len(matches) == 1:
        event_id, player = matches[0]
        return _evaluate_player(parsed, line, player, event_id)
    if len(matches) > 1 or ambiguous:
        return Grade(UNRESOLVED, f"More than one player matches {subject}")
    # Only void on a ruled-out name once every game is over and nobody by that name
    # played. Otherwise a Jaguars linebacker on IR voids a bet on the Bills quarterback.
    if schedule.all_final and len(ruled_out) == 1:
        event_id, status = ruled_out[0]
        return Grade(VOID, f"{subject} was ruled out ({status})", event_id)
    if schedule.all_final:
        return Grade(
            UNRESOLVED,
            f"{subject} isn't in any week {schedule.week} box score -- didn't play, or "
            "the name didn't match",
        )
    return Grade(PENDING, f"Waiting for {subject}'s game")


async def grade_leg(
    parsed: dict | None,
    payer_line: float | None,
    schedule: WeekSchedule,
    load: SummaryLoader,
) -> Grade:
    """Settle one leg, or say plainly why it can't be settled yet."""
    if not parsed:
        return Grade(PENDING, "Not read yet")
    if not parsed.get("understood"):
        return Grade(UNRESOLVED, parsed.get("note") or "Couldn't tell what this bet is")

    market = parsed.get("market")
    if market not in PLAYER_MARKETS and market not in TEAM_MARKETS:
        return Grade(UNRESOLVED, "Not a bet type that can be graded automatically")

    # A recorded line wins over one in the text: it is what was actually placed.
    line = payer_line if payer_line is not None else parsed.get("line")

    # Checked before the game is looked at, so the payer is asked for the line well
    # before kickoff rather than after the leg has already settled.
    if needs_line(parsed, payer_line):
        return Grade(
            NEEDS_LINE, "No line recorded -- enter the line placed, or mark it hit or miss"
        )

    if market in TEAM_MARKETS:
        return await _grade_team(parsed, line, schedule, load)
    return await _grade_player(parsed, line, schedule, load)
