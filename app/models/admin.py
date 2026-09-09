import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ROOM_ADMIN = "ROOM_ADMIN"


class Admin(Base):
    __tablename__ = "admins"

    admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="admin_role", create_type=False),
        default=AdminRole.ROOM_ADMIN,
        nullable=False,
    )
    # Audit §2.9: binds a ROOM_ADMIN to the one room they actually manage.
    # NULL for every SUPER_ADMIN (unrestricted). For backwards compatibility
    # with accounts created before this column existed, a ROOM_ADMIN with
    # room_id still NULL is also left unrestricted by
    # deps.assert_admin_room_access — operators should assign a room_id to
    # every ROOM_ADMIN account going forward via PATCH
    # /admin/admins/{admin_id}/room to actually get the per-room boundary.
    room_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.room_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
