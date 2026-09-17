"""ESPN scoreboard and box score client (unofficial, no API key).

Used for three things: the kickoff time that anchors each submission deadline, whether a
week has actually finished, and the box scores that grade each leg. Sleeper reports points
continuously, so without a finality signal we would happily crown a "loser" halfway through
Sunday afternoon.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dateutil import parser as date_parser

from app.config import settings
from app.integrations.http import get_json

log = logging.getLogger(__name__)

REGULAR_SEASON = 2
MAX_REGULAR_WEEK = 18

# Exactly as ESPN spells them -- WSH, not WAS. The leg parser is constrained to this list,
# since a team the scoreboard does not recognise can never be matched to a game.
TEAM_ABBREVIATIONS = (
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
    "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH",
)  # fmt: skip

# Injury-report statuses that mean a player definitely did not play. The injury block on a
# summary is the pre-game report rather than a game-day inactive list -- a "Questionable"
# player very often plays -- so only statuses that rule a player out can justify voiding a
# leg. Anything softer is left for a person to decide.
RULED_OUT = frozenset(
    {
        "INJURY_STATUS_OUT",
        "INJURY_STATUS_IR",
        "INJURY_STATUS_PUP",
        "INJURY_STATUS_SUSPENSION",
        "INJURY_STATUS_NFI",
    }
)


@dataclass(frozen=True)
class NflEvent:
    event_id: str
    name: str
    kickoff_at: datetime
    status: str
    teams: tuple[str, ...] = ()

    @property
    def is_final(self) -> bool:
        return self.status == "STATUS_FINAL"


@dataclass(frozen=True)
class WeekSchedule:
    season: str
    week: int
    events: list[NflEvent]

    @property
    def first_kickoff_at(self) -> datetime | None:
        return min((e.kickoff_at for e in self.events), default=None)

    @property
    def last_kickoff_at(self) -> datetime | None:
        return max((e.kickoff_at for e in self.events), default=None)

    @property
    def all_final(self) -> bool:
        return bool(self.events) and all(e.is_final for e in self.events)

    def event_for_team(self, abbreviation: str) -> NflEvent | None:
        return next((e for e in self.events if abbreviation in e.teams), None)


@dataclass(frozen=True)
class PlayerLine:
    """One player's box score, flattened across every category they appear in."""

    name: str
    team: str
    stats: dict[str, float] = field(default_factory=dict)

    def stat(self, key: str) -> float:
        # Absent from a category means none of it: a back with no targets is simply not
        # listed under receiving, which is zero receptions rather than unknown.
        return self.stats.get(key, 0.0)


@dataclass(frozen=True)
class GameSummary:
    event_id: str
    status: str
    scores: dict[str, int]
    players: list[PlayerLine]
    # Display name -> ESPN status type, for players ruled out before the game.
    ruled_out: dict[str, str] = field(default_factory=dict)

    @property
    def is_final(self) -> bool:
        return self.status == "STATUS_FINAL"

    def opponent(self, abbreviation: str) -> str | None:
        return next((t for t in self.scores if t != abbreviation), None)


def _parse_dt(value: str) -> datetime:
    dt = date_parser.isoparse(value)
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _num(value) -> float:
    """ESPN serialises every stat as a string, with "--" or "" for none."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


# (category, column label) -> our stat key. Anything not listed is ignored.
_STAT_COLUMNS: dict[tuple[str, str], str] = {
    ("passing", "YDS"): "passing_yards",
    ("passing", "TD"): "passing_touchdowns",
    ("passing", "INT"): "interceptions_thrown",
    ("rushing", "CAR"): "rushing_attempts",
    ("rushing", "YDS"): "rushing_yards",
    ("rushing", "TD"): "rushing_touchdowns",
    ("receiving", "REC"): "receptions",
    ("receiving", "YDS"): "receiving_yards",
    ("receiving", "TD"): "receiving_touchdowns",
    ("receiving", "TGTS"): "targets",
    # Return touchdowns count toward "anytime TD" at the major books, so they are kept.
    ("kickReturns", "TD"): "return_touchdowns",
    ("puntReturns", "TD"): "return_touchdowns",
}


async def get_week_schedule(season: str, week: int) -> WeekSchedule:
    data = await get_json(
        f"{settings.espn_base_url}/scoreboard",
        params={"dates": season, "seasontype": REGULAR_SEASON, "week": week},
    )
    events: list[NflEvent] = []
    for raw in (data or {}).get("events", []):
        try:
            competitors = (raw.get("competitions") or [{}])[0].get("competitors") or []
            events.append(
                NflEvent(
                    event_id=str(raw["id"]),
                    name=raw.get("shortName") or raw.get("name") or "",
                    kickoff_at=_parse_dt(raw["date"]),
                    status=raw.get("status", {}).get("type", {}).get("name", "STATUS_SCHEDULED"),
                    teams=tuple(
                        c["team"]["abbreviation"] for c in competitors if c.get("team")
                    ),
                )
            )
        except (KeyError, ValueError) as exc:
            log.warning("Skipping malformed ESPN event in %s wk%s: %s", season, week, exc)

    return WeekSchedule(season=season, week=week, events=events)


async def _team_roster(abbr: str) -> list[tuple[str, str]]:
    data = await get_json(f"{settings.espn_base_url}/teams/{abbr}/roster")
    return [
        (athlete["fullName"], abbr)
        for group in (data or {}).get("athletes", [])
        for athlete in group.get("items", [])
        if athlete.get("fullName")
    ]


async def get_rosters() -> list[tuple[str, str]]:
    """(player, team) for everyone on an active NFL roster.

    The leg parser cannot know this. A model's roster knowledge is frozen at its training
    cutoff, so a rookie or anyone traded since gets a confidently wrong team -- and a
    wrong team that happens to be playing is worse than none at all.

    Thirty-two requests, run together, come back in well under a second. One team failing
    is logged and skipped rather than costing us the other thirty-one: a partial index
    only means a few legs keep whatever the model guessed.
    """
    results = await asyncio.gather(
        *(_team_roster(abbr) for abbr in TEAM_ABBREVIATIONS), return_exceptions=True
    )
    pairs: list[tuple[str, str]] = []
    for abbr, result in zip(TEAM_ABBREVIATIONS, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("Roster fetch failed for %s: %s", abbr, result)
        else:
            pairs.extend(result)
    return pairs


async def get_game_summary(event_id: str) -> GameSummary | None:
    """Final score, every player's stat line, and who was ruled out, for one game."""
    data = await get_json(f"{settings.espn_base_url}/summary", params={"event": event_id})
    if not data:
        return None

    try:
        competition = data["header"]["competitions"][0]
    except (KeyError, IndexError):
        log.warning("ESPN summary for %s has no competition header", event_id)
        return None

    status = competition.get("status", {}).get("type", {}).get("name", "STATUS_SCHEDULED")
    scores = {
        c["team"]["abbreviation"]: int(_num(c.get("score")))
        for c in competition.get("competitors") or []
        if c.get("team")
    }

    lines: dict[tuple[str, str], dict[str, float]] = {}
    for team_block in (data.get("boxscore") or {}).get("players") or []:
        team = (team_block.get("team") or {}).get("abbreviation", "")
        for category in team_block.get("statistics") or []:
            labels = category.get("labels") or []
            cat_name = category.get("name", "")
            for athlete in category.get("athletes") or []:
                name = (athlete.get("athlete") or {}).get("displayName")
                if not name:
                    continue
                stats = lines.setdefault((team, name), {})
                raw_stats = athlete.get("stats") or []
                for label, value in zip(labels, raw_stats, strict=False):
                    if (cat_name, label) == ("passing", "C/ATT"):
                        made, _, att = str(value).partition("/")
                        stats["completions"] = _num(made)
                        stats["passing_attempts"] = _num(att)
                        continue
                    key = _STAT_COLUMNS.get((cat_name, label))
                    if key:
                        # += because return touchdowns arrive from two categories.
                        stats[key] = stats.get(key, 0.0) + _num(value)

    ruled_out: dict[str, str] = {}
    for team_block in data.get("injuries") or []:
        for row in team_block.get("injuries") or []:
            name = (row.get("athlete") or {}).get("displayName")
            kind = (row.get("type") or {}).get("name", "")
            if name and kind in RULED_OUT:
                ruled_out[name] = row.get("status") or kind

    return GameSummary(
        event_id=str(event_id),
        status=status,
        scores=scores,
        players=[PlayerLine(name=n, team=t, stats=s) for (t, n), s in lines.items()],
        ruled_out=ruled_out,
    )
