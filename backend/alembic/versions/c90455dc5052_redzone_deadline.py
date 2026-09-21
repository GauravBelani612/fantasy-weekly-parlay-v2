"""redzone deadline

Lets a commissioner move the weekly deadline from the first kickoff of the week to the
Sunday RedZone window, and records enough to enforce it:

  leagues.deadline_mode          which kickoff the lock is measured back from
  nfl_weeks.redzone_kickoff_at   when that window opens, cached with the rest of the week
  parlay_rounds.window_opens_at  the earliest kickoff a leg may ride on, per round

deadline_mode carries a server default, so the existing leagues row takes 'first_kickoff'
without a rewrite and nothing changes for a league that never opts in. The other two are
nullable. On Postgres all three are catalogue-only -- safe against a live round.

Revision ID: c90455dc5052
Revises: 92ecde869d7d
Create Date: 2026-09-21 11:42:18.903471

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c90455dc5052"
down_revision: str | Sequence[str] | None = "92ecde869d7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "deadline_mode",
                sa.String(length=32),
                nullable=False,
                server_default="first_kickoff",
            )
        )

    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("redzone_kickoff_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("parlay_rounds", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("window_opens_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("parlay_rounds", schema=None) as batch_op:
        batch_op.drop_column("window_opens_at")

    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.drop_column("redzone_kickoff_at")

    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.drop_column("deadline_mode")
