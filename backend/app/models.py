"""Database models.

Column types are deliberately dialect-portable: local dev runs on SQLite, production on
Neon Postgres, and the same models must work on both. That means JSON (not JSONB/ARRAY)
for structured columns and integer cents (not Numeric) for money.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres, plain JSON on SQLite.
JsonCol = JSON().with_variant(JSONB, "postgresql")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sleeper_link: Mapped["SleeperLink | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class SleeperLink(Base):
    """A user's claimed Sleeper account.

    Sleeper has no OAuth, so ownership cannot be proven. The UNIQUE on sleeper_user_id is
    what enforces "first claim wins" -- once an account is claimed it is locked to that
    Google login and nobody else can take it.
    """

    __tablename__ = "sleeper_links"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    sleeper_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sleeper_username: Mapped[str] = mapped_column(String(255))
    sleeper_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sleeper_avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sleeper_link")


class League(Base):
    __tablename__ = "leagues"
    __table_args__ = (UniqueConstraint("sleeper_league_id", "season", name="uq_league_season"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    sleeper_league_id: Mapped[str] = mapped_column(String(64), index=True)
    season: Mapped[str] = mapped_column(String(8))
    name: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_rosters: Mapped[int] = mapped_column(Integer, default=0)

    # How the weekly payer is chosen. Only 'lowest_points' is implemented today.
    loser_rule: Mapped[str] = mapped_column(String(32), default="lowest_points")
    # Minutes before the target week's first kickoff that submissions lock.
    lock_offset_minutes: Mapped[int] = mapped_column(Integer, default=60)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    # Write-only via the API -- never serialized back to clients.
    discord_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    first_scored_week: Mapped[int] = mapped_column(Integer, default=1)
    last_scored_week: Mapped[int] = mapped_column(Integer, default=17)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["LeagueMember"]] = relationship(
        back_populates="league", cascade="all, delete-orphan"
    )


class LeagueMember(Base):
    """One row per Sleeper roster in the league.

    Rows are created for *every* roster, including people who have not signed up, because
    the lowest-score calculation is only correct if it sees the whole league. A NULL
    user_id means nobody has claimed that roster in this app, so it cannot submit a leg.
    """

    __tablename__ = "league_members"
    __table_args__ = (
        UniqueConstraint("league_id", "sleeper_roster_id", name="uq_member_roster"),
        UniqueConstraint("league_id", "user_id", name="uq_member_user"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    league_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leagues.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sleeper_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sleeper_roster_id: Mapped[int] = mapped_column(Integer)

    display_name: Mapped[str] = mapped_column(String(255))
    team_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="member")

    league: Mapped[League] = relationship(back_populates="members")


class NflWeek(Base):
    """Cached ESPN schedule window for one NFL week -- drives the submission deadline."""

    __tablename__ = "nfl_weeks"

    season: Mapped[str] = mapped_column(String(8), primary_key=True)
    week: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    # True once every ESPN event for the week reports STATUS_FINAL.
    all_final: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeekScore(Base):
    """Cached Sleeper matchup points, so the loser calculation is auditable and replayable."""

    __tablename__ = "week_scores"

    league_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leagues.id", ondelete="CASCADE"), primary_key=True
    )
    season: Mapped[str] = mapped_column(String(8), primary_key=True)
    week: Mapped[int] = mapped_column(Integer, primary_key=True)
    sleeper_roster_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    points: Mapped[float] = mapped_column(Float, default=0.0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParlayRound(Base):
    """One week's parlay: scored_week decides who pays, bet_week is what the legs are on."""

    __tablename__ = "parlay_rounds"
    __table_args__ = (
        UniqueConstraint("league_id", "season", "bet_week", name="uq_round_bet_week"),
        Index("ix_round_league_season", "league_id", "season"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    league_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("leagues.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[str] = mapped_column(String(8))
    scored_week: Mapped[int] = mapped_column(Integer)
    bet_week: Mapped[int] = mapped_column(Integer)

    loser_member_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("league_members.id", ondelete="SET NULL"), nullable=True
    )
    loser_points: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Populated only on a tie for lowest score; requires human resolution.
    tie_roster_ids: Mapped[list | None] = mapped_column(JsonCol, nullable=True)

    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locks_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    outcome: Mapped[str] = mapped_column(String(16), default="pending")
    final_odds: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stake_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payout_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    legs: Mapped[list["Leg"]] = relationship(
        back_populates="round", cascade="all, delete-orphan"
    )


class Leg(Base):
    """One member's contribution to a round. UNIQUE(round_id, member_id) is the
    'one leg per person' rule the Google Form could never enforce."""

    __tablename__ = "legs"
    __table_args__ = (UniqueConstraint("round_id", "member_id", name="uq_leg_round_member"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    round_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parlay_rounds.id", ondelete="CASCADE"), index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_members.id", ondelete="CASCADE"), index=True
    )

    # Exactly what the user typed. Source of truth -- the parsing pass never overwrites this.
    raw_text: Mapped[str] = mapped_column(Text)
    # How the parser read raw_text: player or team, market, direction, line. Written by
    # the parser only, and cleared whenever raw_text changes.
    parsed: Mapped[dict | None] = mapped_column(JsonCol, nullable=True)
    espn_event_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    american_odds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # pending | hit | miss | void | needs_line | unresolved. No push: league rule.
    result: Mapped[str] = mapped_column(String(16), default="pending")

    # The line actually placed, when the typed leg never said one ("Jordan Love over
    # passing yards"). The payer sees the real sportsbook line when placing the bet, so
    # it comes from them. Kept out of `parsed` so re-reading the text can never erase
    # something a person entered.
    payer_line: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Why the leg got its result, in terms a league member can check against the game.
    grade_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Kickoff of the game this leg rides on, so the browser can show it in the reader's
    # own timezone. Times are deliberately kept out of grade_detail: a formatted time
    # baked into a stored sentence can never adapt to who is reading it.
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "espn" when graded from the box score, "manual" when the payer or commissioner set
    # it. The grader never touches a manual result.
    graded_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    round: Mapped[ParlayRound] = relationship(back_populates="legs")
    member: Mapped[LeagueMember] = relationship()


class NotificationLog(Base):
    """Idempotency ledger so a double-firing cron cannot spam the league."""

    __tablename__ = "notifications_log"
    __table_args__ = (
        UniqueConstraint("round_id", "kind", "channel", "target", name="uq_notification_once"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    round_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("parlay_rounds.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    channel: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(320))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
