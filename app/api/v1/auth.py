from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models.admin import Admin
from app.models.team import Team
from app.schemas.auth import AdminLoginRequest, TeamLoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/team/login", response_model=TokenResponse)
async def team_login(payload: TeamLoginRequest, db: AsyncSession = Depends(get_db)):
    team = (
        await db.execute(select(Team).where(Team.team_code == payload.team_code))
    ).scalar_one_or_none()
    if team is None or not verify_password(payload.password, team.password_hash):
        raise UnauthorizedError("Invalid team code or password")

    token = create_access_token(
        subject=str(team.team_id), extra_claims={"type": "team", "team_code": team.team_code}
    )
    return TokenResponse(access_token=token)


@router.post("/admin/login", response_model=TokenResponse)
async def admin_login(payload: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    admin = (
        await db.execute(select(Admin).where(Admin.username == payload.username))
    ).scalar_one_or_none()
    if admin is None or not verify_password(payload.password, admin.password_hash):
        raise UnauthorizedError("Invalid username or password")

    token = create_access_token(
        subject=str(admin.admin_id), extra_claims={"type": "admin", "role": admin.role.value}
    )
    return TokenResponse(access_token=token)
