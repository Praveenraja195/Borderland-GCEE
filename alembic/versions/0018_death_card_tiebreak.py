"""death_card_tiebreak

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-19

Adds the Death Card tiebreaker: tiebreak_sessions / participants / rounds /
picks, plus room_results.tiebreak_pending, which holds a tied team's outcome
(neither qualified nor eliminated on its device) until the tiebreak resolves.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "room_results",
        sa.Column("tiebreak_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "tiebreak_sessions",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rooms.room_id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tie_rank", sa.SmallInteger(), nullable=False),
        sa.Column("tie_total", sa.Numeric(9, 2), nullable=False),
        sa.Column("slots", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tiebreak_sessions_room_id", "tiebreak_sessions", ["room_id"])

    op.create_table(
        "tiebreak_participants",
        sa.Column("participant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiebreak_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ALIVE"),
        sa.Column("eliminated_in_round", sa.SmallInteger(), nullable=True),
        sa.UniqueConstraint("session_id", "team_id"),
    )

    op.create_table(
        "tiebreak_rounds",
        sa.Column("round_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiebreak_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_number", sa.SmallInteger(), nullable=False),
        sa.Column("card_count", sa.SmallInteger(), nullable=False),
        sa.Column("joker_index", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eliminated_team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.team_id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("session_id", "round_number"),
    )

    op.create_table(
        "tiebreak_picks",
        sa.Column("pick_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("round_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiebreak_rounds.round_id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False),
        sa.Column("card_index", sa.SmallInteger(), nullable=False),
        sa.Column("picked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("auto_assigned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("round_id", "card_index"),
        sa.UniqueConstraint("round_id", "team_id"),
    )


def downgrade() -> None:
    op.drop_table("tiebreak_picks")
    op.drop_table("tiebreak_rounds")
    op.drop_table("tiebreak_participants")
    op.drop_index("ix_tiebreak_sessions_room_id", table_name="tiebreak_sessions")
    op.drop_table("tiebreak_sessions")
    op.drop_column("room_results", "tiebreak_pending")
