"""leg grading

Adds what grading a leg needs beyond its result: the line the payer placed when the typed
leg never named one, a readable reason for the result, and who decided it.

All four columns are nullable, so on Postgres this is a catalogue-only change -- no table
rewrite, safe to run against a round that is live.

Revision ID: 3f5f5c5c0cc4
Revises: ed9869fdf610
Create Date: 2026-09-16 22:41:49.146349

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3f5f5c5c0cc4"
down_revision: str | Sequence[str] | None = "ed9869fdf610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("legs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payer_line", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("grade_detail", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("graded_by", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("legs", schema=None) as batch_op:
        batch_op.drop_column("graded_at")
        batch_op.drop_column("graded_by")
        batch_op.drop_column("grade_detail")
        batch_op.drop_column("payer_line")
