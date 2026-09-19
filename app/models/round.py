import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, SmallInteger, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RoundStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class RoomStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Round(Base):
    __tablename__ = "rounds"

    round_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_number: Mapped[int] = mapped_column(SmallInteger, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[RoundStatus] = mapped_column(
        Enum(RoundStatus, name="round_status", create_type=False),
        default=RoundStatus.NOT_STARTED,
        nullable=False,
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set on every "Publish Final Results"; NULL until the admin publishes.
    # Its epoch-ms value is the broadcast id team devices acknowledge against.
    results_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("round_id", "room_number"),
        UniqueConstraint("round_id", "room_code"),
        UniqueConstraint("room_id", "round_id"),
    )

    room_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rounds.round_id", ondelete="CASCADE"), nullable=False
    )
    room_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    room_code: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[RoomStatus] = mapped_column(
        Enum(RoomStatus, name="room_status", create_type=False),
        default=RoomStatus.NOT_STARTED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
