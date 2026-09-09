"""bind ROOM_ADMIN to a room; snapshot session rosters

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13

Backend audit §2.9: adds admins.room_id (nullable FK -> rooms.room_id,
ON DELETE SET NULL) so a ROOM_ADMIN can be bound to the one room they
manage instead of every ROOM_ADMIN implicitly having access to every room.
NULL means "unrestricted" (SUPER_ADMIN, or a not-yet-migrated ROOM_ADMIN
account) — see app/models/admin.py and app/api/deps.py.

Backend audit §2.6: adds game_sessions.roster_team_ids (JSONB, nullable) so
the roster used to backfill no-submit rows at round-close time is the
roster that was actually present when the session started, not whoever
happens to be assigned to the room by the time the close job runs.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE admins ADD COLUMN IF NOT EXISTS room_id UUID "
        "REFERENCES rooms(room_id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_admins_room ON admins(room_id)")
    op.execute("ALTER TABLE game_sessions ADD COLUMN IF NOT EXISTS roster_team_ids JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE game_sessions DROP COLUMN IF EXISTS roster_team_ids")
    op.execute("DROP INDEX IF EXISTS idx_admins_room")
    op.execute("ALTER TABLE admins DROP COLUMN IF EXISTS room_id")
