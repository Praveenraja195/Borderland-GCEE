import uuid
from datetime import datetime

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Numeric, SmallInteger, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoomResult(Base):
    __tablename__ = "room_results"
    __table_args__ = (UniqueConstraint("room_id", "team_id"),)

    result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    mindmaze_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    king_diamond_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    jack_heart_score: Mapped[float] = mapped_column(Numeric(8, 2), default=0, nullable=False)
    total_score: Mapped[float] = mapped_column(
        Numeric(9, 2),
        Computed("mindmaze_score + king_diamond_score + jack_heart_score", persisted=True),
    )
    rank: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QualificationRule(Base):
    __tablename__ = "qualification_rules"
    __table_args__ = (UniqueConstraint("round_id", "room_id"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id"), nullable=True
    )
    top_n: Mapped[int] = mapped_column(SmallInteger, nullable=False)
