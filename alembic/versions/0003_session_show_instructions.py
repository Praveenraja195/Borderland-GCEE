"""add instruction_until to game_sessions, for admin show-instructions

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13

Adds game_sessions.instruction_until, set by admins to broadcast an
instruction screen to team apps for 5 minutes at a time. Team app polls
GET /rooms/{room_id}/sessions and renders the instruction screen while
now() < instruction_until.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS instruction_until TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE game_sessions DROP COLUMN IF EXISTS instruction_until")
