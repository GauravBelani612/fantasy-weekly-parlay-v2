"""League and personal stats, derived from the legs and rounds already stored.

Nothing here is persisted. Every figure is recomputed from results on each request, so a leg
corrected by hand shows up everywhere at once and there is no second copy to drift out of
date. A season is small -- a dozen people over eighteen weeks -- so recomputing costs little.

Counting rules, applied everywhere below:

- Hit rate counts hits and misses only. A void means the player didn't play: it neither helps
  nor hurts a percentage, and neither extends nor breaks a streak.
- Legs still pending, waiting on a line, or unresolved count toward nothing.
- Per-week averages and anything that depends on a week being over ("one leg away", "only
  miss") use finished weeks only -- locked, with every leg settled. Otherwise a Thursday with
  one game graded would drag the averages down, and a leg that is the only miss on Thursday
  could stop being so by Sunday.

The computation takes plain records rather than ORM rows, so every rule can be tested without
a database.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import League, LeagueMember, Leg, ParlayRound

HIT, MISS, VOID = "hit", "miss", "void"
SETTLED = frozenset({HIT, MISS, VOID})

# Parsed market -> the bet type a league member would recognise.
_BET_TYPES = {
    "touchdowns": "Touchdowns",
    "rushing_touchdowns": "Touchdowns",
    "receiving_touchdowns": "Touchdowns",
    "passing_touchdowns": "Touchdowns",
    "passing_yards": "Yards",
    "rushing_yards": "Yards",
    "receiving_yards": "Yards",
    "rushing_and_receiving_yards": "Yards",
    "receptions": "Receptions",
    "completions": "Other props",
    "passing_attempts": "Other props",
    "rushing_attempts": "Other props",
    "interceptions_thrown": "Other props",
    "moneyline": "Moneyline",
    "spread": "Spread",
    "game_total": "Totals",
    "team_total": "Totals",
}

# A personal "best bet type" needs at least this many settled legs, or one lucky week makes
# someone a 100% touchdown specialist.
BEST_TYPE_MIN_LEGS = 2


def bet_type(market: str | None) -> str:
    return _BET_TYPES.get(market or "", "Other")


def _rate(hits: int, misses: int) -> float | None:
    total = hits + misses
    return round(hits / total, 4) if total else None


# ------------------------------------------------------------------------ records in


@dataclass(frozen=True)
class RoundRecord:
    id: uuid.UUID
    bet_week: int
    outcome: str
    loser_member_id: uuid.UUID | None
    locked: bool


@dataclass(frozen=True)
class LegRecord:
    member_id: uuid.UUID
    round_id: uuid.UUID
    bet_week: int
    result: str
    market: str | None


@dataclass(frozen=True)
class MemberRecord:
    id: uuid.UUID
    display_name: str
    avatar_url: str | None
    has_app_account: bool
    is_you: bool


# ------------------------------------------------------------------------ figures out


@dataclass
class Streak:
    result: str
    length: int


@dataclass
class BetType:
    label: str
    hits: int
    misses: int
    hit_rate: float | None


@dataclass
class BestWeek:
    bet_week: int
    hits: int
    legs: int


@dataclass
class Payer:
    member_id: uuid.UUID
    display_name: str
    times: int


@dataclass
class LeagueTotals:
    weeks_complete: int = 0
    legs_hit: int = 0
    legs_missed: int = 0
    hit_rate: float | None = None
    avg_hits_per_week: float | None = None
    avg_legs_per_week: float | None = None
    best_week: BestWeek | None = None
    parlays_won: int = 0
    parlays_lost: int = 0
    cash_rate: float | None = None
    one_leg_away: int = 0
    by_bet_type: list[BetType] = field(default_factory=list)
    # Everyone tied for funding the most parlays. A tie names them all rather than
    # quietly picking one.
    top_payers: list[Payer] = field(default_factory=list)


@dataclass
class MemberStats:
    member_id: uuid.UUID
    display_name: str
    avatar_url: str | None
    is_you: bool
    hits: int = 0
    misses: int = 0
    voids: int = 0
    hit_rate: float | None = None
    current_streak: Streak | None = None
    longest_hit_streak: int = 0
    parlays_played: int = 0
    parlays_won: int = 0
    times_funded: int = 0
    only_miss: int = 0
    best_bet_type: BetType | None = None


@dataclass
class LeagueStats:
    season: str
    league: LeagueTotals
    members: list[MemberStats]


# ------------------------------------------------------------------------ rules


def streaks(results: list[str]) -> tuple[Streak | None, int]:
    """Current run and longest hit run, from results oldest first.

    Voids are skipped entirely -- a player who sat out doesn't reset anyone's streak.
    """
    settled = [r for r in results if r in (HIT, MISS)]
    if not settled:
        return None, 0

    current = Streak(settled[-1], 0)
    for result in reversed(settled):
        if result != current.result:
            break
        current.length += 1

    longest = run = 0
    for result in settled:
        run = run + 1 if result == HIT else 0
        longest = max(longest, run)
    return current, longest


def _bet_types(legs: list[LegRecord]) -> list[BetType]:
    tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for leg in legs:
        if leg.result == HIT:
            tally[bet_type(leg.market)][0] += 1
        elif leg.result == MISS:
            tally[bet_type(leg.market)][1] += 1
    rows = [BetType(label, h, m, _rate(h, m)) for label, (h, m) in tally.items()]
    # Most-bet types first: a 1-for-1 type is less telling than a 6-for-14 one.
    return sorted(rows, key=lambda b: (-(b.hits + b.misses), b.label))


def compute(
    season: str,
    rounds: list[RoundRecord],
    legs: list[LegRecord],
    members: list[MemberRecord],
) -> LeagueStats:
    by_round: dict[uuid.UUID, list[LegRecord]] = defaultdict(list)
    for leg in legs:
        by_round[leg.round_id].append(leg)

    # A week counts for averages once it is locked and every leg in it has settled.
    complete = {
        rnd.id
        for rnd in rounds
        if rnd.locked
        and by_round.get(rnd.id)
        and all(leg.result in SETTLED for leg in by_round[rnd.id])
    }

    totals = LeagueTotals(weeks_complete=len(complete))
    totals.legs_hit = sum(1 for leg in legs if leg.result == HIT)
    totals.legs_missed = sum(1 for leg in legs if leg.result == MISS)
    totals.hit_rate = _rate(totals.legs_hit, totals.legs_missed)

    if complete:
        weeks = [by_round[rid] for rid in complete]
        totals.avg_hits_per_week = round(
            sum(sum(1 for leg in w if leg.result == HIT) for w in weeks) / len(weeks), 2
        )
        totals.avg_legs_per_week = round(sum(len(w) for w in weeks) / len(weeks), 2)

    # Best week counts any week so far: a hit tally only ever grows, so a week in progress
    # can only understate itself. Ties go to the earliest, the week that set the mark.
    best = None
    for rnd in sorted(rounds, key=lambda r: r.bet_week):
        week_legs = by_round.get(rnd.id, [])
        hits = sum(1 for leg in week_legs if leg.result == HIT)
        if hits and (best is None or hits > best.hits):
            best = BestWeek(rnd.bet_week, hits, len(week_legs))
    totals.best_week = best

    totals.parlays_won = sum(1 for rnd in rounds if rnd.outcome == "won")
    totals.parlays_lost = sum(1 for rnd in rounds if rnd.outcome == "lost")
    totals.cash_rate = _rate(totals.parlays_won, totals.parlays_lost)
    totals.one_leg_away = sum(
        1
        for rnd in rounds
        if rnd.outcome == "lost"
        and rnd.id in complete
        and sum(1 for leg in by_round[rnd.id] if leg.result == MISS) == 1
    )
    totals.by_bet_type = _bet_types(legs)

    outcome = {rnd.id: rnd.outcome for rnd in rounds}
    funded: dict[uuid.UUID, int] = defaultdict(int)
    for rnd in rounds:
        if rnd.loser_member_id:
            funded[rnd.loser_member_id] += 1

    names = {m.id: m.display_name for m in members}
    if funded:
        most = max(funded.values())
        totals.top_payers = sorted(
            (Payer(mid, names[mid], n) for mid, n in funded.items() if n == most and mid in names),
            key=lambda p: p.display_name.lower(),
        )

    # The only miss in a finished week: that leg alone cost the league the parlay.
    only_miss: dict[uuid.UUID, int] = defaultdict(int)
    for rid in complete:
        misses = [leg for leg in by_round[rid] if leg.result == MISS]
        if len(misses) == 1:
            only_miss[misses[0].member_id] += 1

    by_member: dict[uuid.UUID, list[LegRecord]] = defaultdict(list)
    for leg in sorted(legs, key=lambda leg: leg.bet_week):
        by_member[leg.member_id].append(leg)

    out: list[MemberStats] = []
    for member in members:
        mine = by_member.get(member.id, [])
        # Rosters nobody has claimed, that never bet or paid, are just noise here.
        if not member.has_app_account and not mine and not funded.get(member.id):
            continue

        stats = MemberStats(member.id, member.display_name, member.avatar_url, member.is_you)
        stats.hits = sum(1 for leg in mine if leg.result == HIT)
        stats.misses = sum(1 for leg in mine if leg.result == MISS)
        stats.voids = sum(1 for leg in mine if leg.result == VOID)
        stats.hit_rate = _rate(stats.hits, stats.misses)
        stats.current_streak, stats.longest_hit_streak = streaks([leg.result for leg in mine])

        played = [outcome[leg.round_id] for leg in mine if leg.round_id in outcome]
        stats.parlays_played = sum(1 for o in played if o in ("won", "lost", "void"))
        stats.parlays_won = sum(1 for o in played if o == "won")
        stats.times_funded = funded.get(member.id, 0)
        stats.only_miss = only_miss.get(member.id, 0)

        eligible = [b for b in _bet_types(mine) if b.hits + b.misses >= BEST_TYPE_MIN_LEGS]
        if eligible:
            stats.best_bet_type = max(eligible, key=lambda b: (b.hit_rate or 0, b.hits))
        out.append(stats)

    # Leaderboard order: most hits, then the better rate, then name for a stable order.
    out.sort(key=lambda s: (-s.hits, -(s.hit_rate or 0), s.display_name.lower()))
    return LeagueStats(season=season, league=totals, members=out)


# ------------------------------------------------------------------------ loading


async def league_stats(
    session: AsyncSession,
    league: League,
    current_user_id: uuid.UUID | None,
    avatar_url,
) -> LeagueStats:
    now = datetime.now(UTC)

    def locked(rnd: ParlayRound) -> bool:
        lock = rnd.locks_at if rnd.locks_at.tzinfo else rnd.locks_at.replace(tzinfo=UTC)
        return now >= lock

    rounds = (
        await session.scalars(select(ParlayRound).where(ParlayRound.league_id == league.id))
    ).all()
    week_of = {rnd.id: rnd.bet_week for rnd in rounds}

    legs = (
        await session.scalars(
            select(Leg).join(ParlayRound, Leg.round_id == ParlayRound.id).where(
                ParlayRound.league_id == league.id
            )
        )
    ).all()
    members = (
        await session.scalars(select(LeagueMember).where(LeagueMember.league_id == league.id))
    ).all()

    return compute(
        season=league.season,
        rounds=[
            RoundRecord(r.id, r.bet_week, r.outcome, r.loser_member_id, locked(r)) for r in rounds
        ],
        legs=[
            LegRecord(
                leg.member_id,
                leg.round_id,
                week_of[leg.round_id],
                leg.result,
                (leg.parsed or {}).get("market"),
            )
            for leg in legs
        ],
        members=[
            MemberRecord(
                m.id,
                m.display_name,
                avatar_url(m.avatar),
                m.user_id is not None,
                current_user_id is not None and m.user_id == current_user_id,
            )
            for m in members
        ],
    )
