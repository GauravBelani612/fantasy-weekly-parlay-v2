"""sunday window

The betting window now opens with the first Sunday kickoff rather than the 1pm slate, so
the international morning game counts. That makes "redzone" the wrong word for it:

  nfl_weeks.redzone_kickoff_at -> nfl_weeks.sunday_kickoff_at
  leagues.deadline_mode 'sunday_redzone' -> 'sunday'

The column holds a derived cache that repopulates on the next schedule sync, so a rename
loses nothing even if the value were dropped. The mode value is rewritten rather than left
to fall through to 'first_kickoff', which would silently hand a league back its Thursday
deadline.

Revision ID: b7e14a2f8c31
Revises: c90455dc5052
Create Date: 2026-09-21 14:18:52.610394

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e14a2f8c31"
down_revision: str | Sequence[str] | None = "c90455dc5052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.alter_column(
            "redzone_kickoff_at",
            new_column_name="sunday_kickoff_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )

    op.execute(
        "UPDATE leagues SET deadline_mode = 'sunday' WHERE deadline_mode = 'sunday_redzone'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE leagues SET deadline_mode = 'sunday_redzone' WHERE deadline_mode = 'sunday'"
    )

    with op.batch_alter_table("nfl_weeks", schema=None) as batch_op:
        batch_op.alter_column(
            "sunday_kickoff_at",
            new_column_name="redzone_kickoff_at",
            existing_type=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
