"""leg kickoff

Stores when the game a leg rides on starts, so the browser can say "Waiting on CIN @ HOU
- Sun 1:00 PM" in whatever timezone the reader is actually in. A formatted time baked
into grade_detail could only ever be right for one of them.

Nullable, so on Postgres this is a catalogue-only change -- no table rewrite, safe to run
against a round that is live. Existing legs fill theirs in on the next grading tick.

Revision ID: 92ecde869d7d
Revises: 3f5f5c5c0cc4
Create Date: 2026-09-17 10:12:03.281447

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "92ecde869d7d"
down_revision: str | Sequence[str] | None = "3f5f5c5c0cc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("legs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kickoff_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("legs", schema=None) as batch_op:
        batch_op.drop_column("kickoff_at")
