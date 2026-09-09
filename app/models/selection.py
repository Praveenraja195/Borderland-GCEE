import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Suit(Base):
    __tablename__ = "suits"

    suit_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)


class Round1Selection(Base):
    __tablename__ = "round1_selections"
    __table_args__ = (
        UniqueConstraint("round_id", "team_id"),
        # Audit Issue 5: without this, two teams from the same suit could
        # simultaneously pick the same number and collide in trg_assign_room.
        UniqueConstraint("round_id", "suit_id", "selected_number", name="uq_suit_number_per_round"),
    )

    selection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    suit_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("suits.suit_id"), nullable=False)
    selected_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id"), nullable=True
    )
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suit: Mapped[Suit] = relationship("Suit", lazy="joined")

    @property
    def suit_code(self) -> str | None:
        return self.suit.code if self.suit else None
