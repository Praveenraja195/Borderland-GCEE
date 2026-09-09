"""add team_view_acks

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-15 14:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()
    if 'team_view_acks' not in tables:
        op.create_table(
            'team_view_acks',
            sa.Column('ack_id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('game_sessions.session_id', ondelete='CASCADE'), nullable=False),
            sa.Column('team_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('teams.team_id', ondelete='CASCADE'), nullable=False),
            sa.Column('round_id', postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column('view_type', sa.String(50), nullable=False),
            sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.UniqueConstraint('session_id', 'team_id', 'view_type', 'round_id', name='uq_team_view_ack')
        )
        op.create_index('idx_team_view_acks_session', 'team_view_acks', ['session_id'])
        op.create_index('idx_team_view_acks_team', 'team_view_acks', ['team_id'])


def downgrade() -> None:
    op.drop_index('idx_team_view_acks_team', table_name='team_view_acks')
    op.drop_index('idx_team_view_acks_session', table_name='team_view_acks')
    op.drop_table('team_view_acks')
