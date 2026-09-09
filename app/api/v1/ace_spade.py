import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.db.session import get_db
from app.models.team import Team
from app.schemas.ace_spade import AceSpadeResultOut, AceSpadeSubmitRequest
from app.services import ace_spade_service

router = APIRouter(prefix="/ace-spade", tags=["ace_spade"])


@router.post(
    "/rounds/{round_id}/submit", response_model=AceSpadeResultOut, status_code=status.HTTP_201_CREATED
)
async def submit_ace_spade_result(
    round_id: uuid.UUID,
    payload: AceSpadeSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await ace_spade_service.submit_result(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
        moves=payload.moves,
        wrong_picks=payload.wrong_picks,
        correct_picks=payload.correct_picks,
        completion_time_seconds=payload.completion_time_seconds,
    )


@router.get("/rooms/{room_id}/leaderboard", response_model=list)
async def get_ace_spade_room_leaderboard(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await ace_spade_service.get_room_leaderboard(
        db,
        room_id=room_id,
        current_team_id=current_team.team_id,
    )
