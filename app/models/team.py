import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Team(Base):
    __tablename__ = "teams"

    team_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    team_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Filled by the bulk registration import (team_import_service); the team's
    # password is derived from leader_phone. Nullable because a team created
    # through the single-team admin form has no leader attached. Migration 0010.
    leader_name: Mapped[str | None] = mapped_column(String, nullable=True)
    leader_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    leader_email: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
