"""add is_published to game_sessions, for admin leaderboard reveal

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-15

Adds game_sessions.is_published, set to true when admin publishes scores/leaderboard
to team screens.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE game_sessions DROP COLUMN IF EXISTS is_published")
