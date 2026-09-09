"""add PAUSED session status + paused_at, for admin pause/resume/restart

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

Adds the pieces needed for admin session control on event day:
  * PAUSED value on the session_status enum (IN_PROGRESS <-> PAUSED)
  * game_sessions.paused_at, so resume can compute the pause duration and
    push every open round's deadline back by the same amount

ALTER TYPE ... ADD VALUE cannot run inside the same transaction that later
uses the new value, and on some PG versions can't run in a transaction
block at all — so it's issued in its own autocommit block, separate from
the ADD COLUMN below.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE session_status ADD VALUE IF NOT EXISTS 'PAUSED'")

    op.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE, so removing PAUSED from the
    # enum requires rebuilding the type (create new type, cast the column
    # over, drop the old type, rename). Not attempted here — pausing is
    # additive and safe to leave in place; drop the column only.
    op.execute("ALTER TABLE game_sessions DROP COLUMN IF EXISTS paused_at")
