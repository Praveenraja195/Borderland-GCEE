import uuid
from datetime import datetime, timedelta

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Interval,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JHSymbol(Base):
    __tablename__ = "jh_symbols"

    symbol_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    suit: Mapped[str | None] = mapped_column(String, nullable=True)
    rank: Mapped[str | None] = mapped_column(String, nullable=True)


class JackHeartRound(Base):
    __tablename__ = "jack_heart_rounds"
    __table_args__ = (UniqueConstraint("session_id", "round_number"),)

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JackHeartAssignment(Base):
    __tablename__ = "jack_heart_assignments"
    __table_args__ = (
        UniqueConstraint("round_id", "team_id"),
        UniqueConstraint("round_id", "symbol_id"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jack_heart_rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    symbol_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("jh_symbols.symbol_id"), nullable=False)


class JackHeartAnswer(Base):
    __tablename__ = "jack_heart_answers"
    __table_args__ = (UniqueConstraint("round_id", "team_id"),)

    answer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jack_heart_rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    submitted_symbol_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("jh_symbols.symbol_id"), nullable=False)
    actual_symbol_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("jh_symbols.symbol_id"), nullable=False)
    is_correct: Mapped[bool] = mapped_column(
        Boolean, Computed("submitted_symbol_id = actual_symbol_id", persisted=True)
    )
    round_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    time_taken: Mapped[timedelta | None] = mapped_column(Interval, nullable=True)
