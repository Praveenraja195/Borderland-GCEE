import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KingDiamondRound(Base):
    __tablename__ = "king_diamond_rounds"
    __table_args__ = (UniqueConstraint("session_id", "round_number"),)

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("game_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    average_value: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    winner_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("king_diamond_submissions.submission_id"), nullable=True
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class KingDiamondSubmission(Base):
    __tablename__ = "king_diamond_submissions"
    __table_args__ = (UniqueConstraint("round_id", "team_id"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("king_diamond_rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    submitted_number: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    difference: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    round_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
