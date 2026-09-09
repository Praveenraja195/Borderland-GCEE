import enum
import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Interval,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class Game(Base):
    __tablename__ = "games"

    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    total_rounds: Mapped[int] = mapped_column(SmallInteger, default=5, nullable=False)


class RoundGames(Base):
    __tablename__ = "round_games"
    __table_args__ = (UniqueConstraint("round_id", "game_order"),)

    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), primary_key=True
    )
    game_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("games.game_id"), primary_key=True
    )
    game_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class GameSession(Base):
    __tablename__ = "game_sessions"
    __table_args__ = (
        UniqueConstraint("room_id", "game_id"),
        ForeignKeyConstraint(["room_id", "round_id"], ["rooms.room_id", "rooms.round_id"]),
        ForeignKeyConstraint(["round_id", "game_id"], ["round_games.round_id", "round_games.game_id"]),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id", ondelete="CASCADE"), nullable=False
    )
    game_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("games.game_id"), nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status", create_type=False),
        default=SessionStatus.NOT_STARTED,
        nullable=False,
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when an admin pauses an IN_PROGRESS session; cleared on resume.
    # Used on resume to compute how long the pause lasted so every open
    # round's deadline can be pushed back by the same amount.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set by admin to broadcast instructions to team screens for 5 minutes.
    # Team app reads this field on every poll and renders the instruction screen
    # until the timestamp passes.
    instruction_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit §2.6: snapshot of team_ids (as strings) selected into this room
    # at the moment start_session() ran, taken from round1_selections. Close
    # jobs (app/workers/jobs.py) roll up scores against THIS list instead of
    # re-querying round1_selections live, so a team moved in/out of the room
    # mid-event (see admin_service.move_team_room) can't desync the roster
    # used to backfill no-submit rows from the roster that actually played.
    # Nullable so sessions created before this column existed still work
    # (callers fall back to the live query when this is NULL).
    roster_team_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Set to true when admin clicks "Publish to Teams", revealing the team leaderboard.
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GameScore(Base):
    __tablename__ = "game_scores"
    __table_args__ = (UniqueConstraint("session_id", "team_id"),)

    score_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    time_taken: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamViewAck(Base):
    __tablename__ = "team_view_acks"
    __table_args__ = (
        UniqueConstraint("session_id", "team_id", "view_type", "round_id", name="uq_team_view_ack"),
    )

    ack_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    round_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    view_type: Mapped[str] = mapped_column(String(50), nullable=False)
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

