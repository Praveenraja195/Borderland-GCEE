"""apply round1_schema.sql as-is

Revision ID: 0001
Revises:
Create Date: 2026-08-11

Per the design doc §4/§12: the schema is triggers/functions/constraints-
heavy, so the first revision just applies sql/round1_schema.sql verbatim
rather than trying to express it through ORM autogenerate. Later
schema changes should get their own revisions, split to match the schema's
own sections (tables -> triggers/functions -> views), using op.execute(...)
for anything Alembic can't diff from the ORM models.
"""

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "round1_schema.sql"


def _load_schema_sql() -> str:
    return _SQL_PATH.read_text()


from sqlalchemy.util import await_only

def upgrade() -> None:
    bind = op.get_bind()
    sql = _load_schema_sql()
    if hasattr(bind, "connection") and hasattr(bind.connection, "dbapi_connection"):
        dbapi_conn = bind.connection.dbapi_connection
        if hasattr(dbapi_conn, "_connection"):
            await_only(dbapi_conn._connection.execute(sql))
            return
    op.execute(sql)


def downgrade() -> None:
    # Destructive on purpose: this is the schema's origin revision. Dropping
    # views/tables/types in dependency order to fully reverse it.
    op.execute(
        """
        DROP VIEW IF EXISTS v_game_leaderboard;
        DROP VIEW IF EXISTS v_overall_leaderboard;
        DROP VIEW IF EXISTS v_room_leaderboard;

        DROP TABLE IF EXISTS qualification_rules CASCADE;
        DROP TABLE IF EXISTS room_results CASCADE;
        DROP TABLE IF EXISTS jack_heart_answers CASCADE;
        DROP TABLE IF EXISTS jack_heart_assignments CASCADE;
        DROP TABLE IF EXISTS jack_heart_rounds CASCADE;
        DROP TABLE IF EXISTS jh_symbols CASCADE;
        DROP TABLE IF EXISTS king_diamond_submissions CASCADE;
        DROP TABLE IF EXISTS king_diamond_rounds CASCADE;
        DROP TABLE IF EXISTS mindmaze_results CASCADE;
        DROP TABLE IF EXISTS mindmaze_rounds CASCADE;
        DROP TABLE IF EXISTS game_scores CASCADE;
        DROP TABLE IF EXISTS game_sessions CASCADE;
        DROP TABLE IF EXISTS round1_selections CASCADE;
        DROP TABLE IF EXISTS round_games CASCADE;
        DROP TABLE IF EXISTS games CASCADE;
        DROP TABLE IF EXISTS rooms CASCADE;
        DROP TABLE IF EXISTS teams CASCADE;
        DROP TABLE IF EXISTS suits CASCADE;
        DROP TABLE IF EXISTS rounds CASCADE;
        DROP TABLE IF EXISTS admins CASCADE;

        DROP FUNCTION IF EXISTS fn_touch_updated_at CASCADE;
        DROP FUNCTION IF EXISTS fn_compute_room_results CASCADE;
        DROP FUNCTION IF EXISTS fn_close_king_diamond_round CASCADE;
        DROP FUNCTION IF EXISTS fn_validate_jh_answer CASCADE;
        DROP FUNCTION IF EXISTS fn_kd_validate_submission CASCADE;
        DROP FUNCTION IF EXISTS fn_prevent_selection_update CASCADE;
        DROP FUNCTION IF EXISTS fn_assign_room CASCADE;
        DROP FUNCTION IF EXISTS fn_enforce_team_cap CASCADE;

        DROP TYPE IF EXISTS admin_role;
        DROP TYPE IF EXISTS session_status;
        DROP TYPE IF EXISTS room_status;
        DROP TYPE IF EXISTS round_status;
        """
    )
