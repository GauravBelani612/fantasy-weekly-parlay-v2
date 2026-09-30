"""monday option

A league can keep Monday games out of the parlay, so the week is over on Sunday night:

  leagues.allow_monday             the setting, on by default
  nfl_weeks.monday_kickoff_at      when Monday football starts, cached with the week
  parlay_rounds.window_closes_at   the latest kickoff a leg may ride on, exclusive

allow_monday carries a server default of true, so every existing league keeps the behaviour
it has today without a rewrite. On Postgres all three are catalogue-only -- safe against a
live round.

Revision ID: 72cf1c41e79f
Revises: b7e14a2f8c31
Create Date: 2026-09-29 09:31:07.482915

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "72cf1c41e79f"
down_revision: str | Sequence[str] | None = "b7e14a2f8c31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("allow_monday", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("monday_kickoff_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("parlay_rounds", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("window_closes_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("parlay_rounds", schema=None) as batch_op:
        batch_op.drop_column("window_closes_at")

    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.drop_column("monday_kickoff_at")

    with op.batch_alter_table("leagues", schema=None) as batch_op:
        batch_op.drop_column("allow_monday")
