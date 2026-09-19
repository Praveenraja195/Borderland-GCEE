"""Death Card tiebreaker.

When two or more teams finish a room on the same total and that tie straddles
the qualification cutoff (top_n), the publish step holds just those teams and
opens a TiebreakSession for the room. Each round the server deals
`alive + 1` face-down cards, one of which is the Joker; every alive team
claims a distinct card; the Joker's holder is eliminated. Rounds repeat until
the number of survivors equals the number of open slots — so the game cannot
end in a tie.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TiebreakStatus(str, enum.Enum):
    PENDING = "PENDING"      # created at publish, not started by the admin yet
    ACTIVE = "ACTIVE"        # rounds running
    COMPLETED = "COMPLETED"  # survivors == slots; outcomes written to room_results
    VOID = "VOID"            # scores changed underneath it; superseded


class TiebreakParticipantStatus(str, enum.Enum):
    ALIVE = "ALIVE"
    ELIMINATED = "ELIMINATED"
    WINNER = "WINNER"


class TiebreakSession(Base):
    __tablename__ = "tiebreak_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id", ondelete="CASCADE"), nullable=False, index=True
    )
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    # The shared rank the tied group sits at, its total, and how many of the
    # tied teams can still qualify. Used to re-validate the session after a
    # recompute: if the tie no longer exists the session is VOID.
    tie_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    tie_total: Mapped[float] = mapped_column(Numeric(9, 2), nullable=False)
    slots: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=TiebreakStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TiebreakParticipant(Base):
    __tablename__ = "tiebreak_participants"
    __table_args__ = (UniqueConstraint("session_id", "team_id"),)

    participant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiebreak_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default=TiebreakParticipantStatus.ALIVE.value, nullable=False)
    eliminated_in_round: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class TiebreakRound(Base):
    __tablename__ = "tiebreak_rounds"
    __table_args__ = (UniqueConstraint("session_id", "round_number"),)

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiebreak_sessions.session_id", ondelete="CASCADE"), nullable=False
    )
    round_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    card_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Chosen before any pick; never sent to devices until the round resolves.
    joker_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminated_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="SET NULL"), nullable=True
    )


class TiebreakPick(Base):
    __tablename__ = "tiebreak_picks"
    __table_args__ = (
        UniqueConstraint("round_id", "card_index"),  # a card can be claimed once
        UniqueConstraint("round_id", "team_id"),     # a team claims one card
    )

    pick_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiebreak_rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.team_id", ondelete="CASCADE"), nullable=False
    )
    card_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    picked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # True when the server dealt the card because the team did not pick in time.
    auto_assigned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
