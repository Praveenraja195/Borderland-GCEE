import uuid

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.admin import Admin, AdminRole
from app.models.team import Team

team_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/team/login", auto_error=False)
admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/admin/login", auto_error=False)


async def get_current_team(
    token: str | None = Depends(team_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Team:
    if token is None:
        raise UnauthorizedError("Missing or invalid team credentials")
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise UnauthorizedError("Missing or invalid team credentials") from exc

    if payload.get("type") != "team":
        raise UnauthorizedError("Not a team token")

    team_id = payload.get("sub")
    team = await db.get(Team, uuid.UUID(team_id))
    if team is None:
        raise UnauthorizedError("Team not found")
    return team


async def get_current_admin(
    token: str | None = Depends(admin_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Admin:
    if token is None:
        raise UnauthorizedError("Missing or invalid admin credentials")
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise UnauthorizedError("Missing or invalid admin credentials") from exc

    if payload.get("type") != "admin":
        raise UnauthorizedError("Not an admin token")

    admin_id = payload.get("sub")
    admin = await db.get(Admin, uuid.UUID(admin_id))
    if admin is None:
        raise UnauthorizedError("Admin not found")
    return admin


def require_role(role: AdminRole):
    async def _check(admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role != role and admin.role != AdminRole.SUPER_ADMIN:
            raise ForbiddenError(f"Requires role {role.value}")
        return admin

    return _check


def assert_admin_room_access(admin: Admin, room_id: uuid.UUID) -> None:
    """Audit §2.9: require_role only ever checked *which* role an admin has,
    never *which room* a ROOM_ADMIN is allowed to touch — so any ROOM_ADMIN
    could start/stop/force-close a session in every room, not just their
    own. Call this after require_role(AdminRole.ROOM_ADMIN) in any
    single-room session-control route, once the target room_id is known
    (directly from the path, or resolved from a session_id/round_id).

    SUPER_ADMIN is always allowed. A ROOM_ADMIN with room_id still NULL
    (not yet migrated to the new binding) is also allowed, for backwards
    compatibility — see the comment on Admin.room_id.
    """
    if admin.role == AdminRole.ROOM_ADMIN and admin.room_id is not None and admin.room_id != room_id:
        raise ForbiddenError("You are not the admin assigned to this room")
