"""API response/request models.

Note what is deliberately absent: League never exposes discord_webhook_url. It is
write-only through the settings endpoint.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None = None


class SleeperLinkOut(BaseModel):
    sleeper_user_id: str
    sleeper_username: str
    sleeper_display_name: str | None = None
    avatar_url: str | None = None


class MeOut(BaseModel):
    user: UserOut
    sleeper: SleeperLinkOut | None = None


class ClaimSleeperIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)


class SleeperLeagueOut(BaseModel):
    """A league available to import, straight from Sleeper."""

    sleeper_league_id: str
    name: str
    season: str
    total_rosters: int
    avatar_url: str | None = None
    already_imported: bool = False
    # Sleeper leagues that were created and abandoned keep showing up in the account's
    # league list forever, indistinguishable by name from the real one. A league nobody
    # finished configuring has no playoff week, which is the one field that separates
    # them reliably -- status stays "in_season" on both.
    unconfigured: bool = False


class ImportLeagueIn(BaseModel):
    sleeper_league_id: str = Field(min_length=1, max_length=64)


class LeagueSettingsIn(BaseModel):
    lock_offset_minutes: int | None = Field(default=None, ge=0, le=10080)
    timezone: str | None = Field(default=None, max_length=64)
    first_scored_week: int | None = Field(default=None, ge=1, le=18)
    last_scored_week: int | None = Field(default=None, ge=1, le=18)
    discord_webhook_url: str | None = Field(default=None, max_length=2048)


class MemberOut(BaseModel):
    id: uuid.UUID
    display_name: str
    team_name: str | None = None
    avatar_url: str | None = None
    sleeper_roster_id: int
    role: str
    has_app_account: bool
    is_you: bool = False


class LeagueOut(BaseModel):
    id: uuid.UUID
    sleeper_league_id: str
    name: str
    season: str
    avatar_url: str | None = None
    total_rosters: int
    lock_offset_minutes: int
    timezone: str
    first_scored_week: int
    last_scored_week: int
    has_discord_webhook: bool = False
    your_role: str | None = None


class LeagueDetailOut(LeagueOut):
    members: list[MemberOut] = []


class LegOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    member_name: str
    member_avatar_url: str | None = None
    raw_text: str
    result: str
    american_odds: int | None = None
    created_at: datetime
    updated_at: datetime
    is_you: bool = False

    # How the leg was understood, e.g. "Chase Brown (CIN) · anytime TD". Shown under the
    # leg so a misreading is noticed by the league before kickoff, not after grading.
    read_as: str | None = None
    # Why it got its result: "Jordan Love: 247 passing yds, line over 224.5".
    grade_detail: str | None = None
    # "espn" or "manual".
    graded_by: str | None = None
    payer_line: float | None = None
    # No line anywhere yet: the payer should record one, or settle the leg by hand.
    needs_line: bool = False
    # Kickoff of the game this leg is waiting on, rendered in the reader's own timezone
    # by the browser.
    kickoff_at: datetime | None = None


class LegSettleIn(BaseModel):
    """The payer or commissioner recording a line, or settling a leg by hand.

    Both fields are optional and only the ones sent are applied, so `{"line": null}`
    clears a recorded line while omitting `line` leaves it alone.
    """

    line: float | None = Field(default=None, allow_inf_nan=False)
    result: Literal["hit", "miss", "void", "pending"] | None = None


class LegIn(BaseModel):
    raw_text: str = Field(min_length=2, max_length=500)


class RoundOut(BaseModel):
    id: uuid.UUID
    league_id: uuid.UUID
    season: str
    scored_week: int
    bet_week: int
    status: str
    opens_at: datetime
    locks_at: datetime

    loser: MemberOut | None = None
    loser_points: float | None = None
    tie_roster_ids: list[int] | None = None
    loser_has_app_account: bool = False

    outcome: str
    final_odds: str | None = None
    stake_cents: int | None = None
    payout_cents: int | None = None
    notes: str | None = None

    legs: list[LegOut] = []
    awaiting: list[MemberOut] = []
    submitted_count: int = 0
    eligible_count: int = 0
    your_leg: LegOut | None = None
    you_can_submit: bool = False


class RoundResultIn(BaseModel):
    outcome: str | None = Field(default=None, pattern="^(pending|won|lost|void)$")
    final_odds: str | None = Field(default=None, max_length=32)
    stake_cents: int | None = Field(default=None, ge=0)
    payout_cents: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)


class SetLoserIn(BaseModel):
    member_id: uuid.UUID


# ---------------------------------------------------------------- stats


class StreakOut(BaseModel):
    result: Literal["hit", "miss"]
    length: int


class BetTypeOut(BaseModel):
    label: str
    hits: int
    misses: int
    hit_rate: float | None = None


class BestWeekOut(BaseModel):
    bet_week: int
    hits: int
    legs: int


class PayerOut(BaseModel):
    member_id: uuid.UUID
    display_name: str
    times: int


class LeagueTotalsOut(BaseModel):
    # Weeks locked with every leg settled; the per-week averages are over these only.
    weeks_complete: int
    legs_hit: int
    legs_missed: int
    hit_rate: float | None = None
    avg_hits_per_week: float | None = None
    avg_legs_per_week: float | None = None
    best_week: BestWeekOut | None = None
    parlays_won: int
    parlays_lost: int
    cash_rate: float | None = None
    # Lost parlays where exactly one leg missed.
    one_leg_away: int
    by_bet_type: list[BetTypeOut] = []
    # Everyone tied for funding the most parlays.
    top_payers: list[PayerOut] = []


class MemberStatsOut(BaseModel):
    member_id: uuid.UUID
    display_name: str
    avatar_url: str | None = None
    is_you: bool = False
    hits: int
    misses: int
    voids: int
    hit_rate: float | None = None
    current_streak: StreakOut | None = None
    longest_hit_streak: int
    parlays_played: int
    parlays_won: int
    times_funded: int
    # Finished weeks where this member's leg was the only miss.
    only_miss: int
    best_bet_type: BetTypeOut | None = None


class LeagueStatsOut(BaseModel):
    season: str
    league: LeagueTotalsOut
    # Leaderboard order: most hits, then hit rate.
    members: list[MemberStatsOut]
