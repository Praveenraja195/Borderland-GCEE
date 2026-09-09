import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Integer, Interval, Numeric, SmallInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AceSpadeRound(Base):
    __tablename__ = "ace_spade_rounds"
    __table_args__ = (UniqueConstraint("session_id", "round_number"),)

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AceSpadeResult(Base):
    __tablename__ = "ace_spade_results"
    __table_args__ = (UniqueConstraint("round_id", "team_id"),)

    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ace_spade_rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    moves: Mapped[int] = mapped_column(Integer, nullable=False)
    wrong_picks: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_picks: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_time: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
    round_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
