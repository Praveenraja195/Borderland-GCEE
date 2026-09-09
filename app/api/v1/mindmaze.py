import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.db.session import get_db
from app.models.team import Team
from app.schemas.mindmaze import MindmazeResultOut, MindmazeSubmitRequest
from app.services import mindmaze_service

router = APIRouter(prefix="/mindmaze", tags=["mindmaze"])


@router.post(
    "/rounds/{round_id}/submit", response_model=MindmazeResultOut, status_code=status.HTTP_201_CREATED
)
async def submit_mindmaze_result(
    round_id: uuid.UUID,
    payload: MindmazeSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await mindmaze_service.submit_result(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
        moves=payload.moves,
        mistakes=payload.mistakes,
        correct_tiles=payload.correct_tiles,
        completion_time_seconds=payload.completion_time_seconds,
    )


@router.get("/rooms/{room_id}/leaderboard", response_model=list)
async def get_mindmaze_room_leaderboard(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await mindmaze_service.get_room_leaderboard(
        db,
        room_id=room_id,
        current_team_id=current_team.team_id,
    )

