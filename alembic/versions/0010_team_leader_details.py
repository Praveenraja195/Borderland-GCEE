"""add leader contact details to teams, for spreadsheet import + winners export

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-07 10:00:00.000000

Teams used to carry nothing but a code, a display name and a password hash.
The bulk registration import (app/services/team_import_service.py) reads a
leader row per team and derives the team's password from the leader's phone
number, and the Round 2 winners export
(app/services/export_service.py) has to be able to actually reach the
qualifying teams — so the leader's name/phone/email are stored alongside
the team rather than thrown away at import time.

All three columns are nullable: teams created through the older single-team
form (POST /admin/teams) still have no leader attached, and that stays valid.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


_COLUMNS = (
    ('leader_name', sa.Text()),
    ('leader_phone', sa.Text()),
    ('leader_email', sa.Text()),
)


def upgrade() -> None:
    conn = op.get_bind()
    existing = {c['name'] for c in sa.inspect(conn).get_columns('teams')}
    for name, type_ in _COLUMNS:
        if name not in existing:
            op.add_column('teams', sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    existing = {c['name'] for c in sa.inspect(conn).get_columns('teams')}
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column('teams', name)
