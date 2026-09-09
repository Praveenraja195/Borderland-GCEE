import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.db.session import get_db
from app.models.team import Team
from app.schemas.jack_heart import JackHeartAnswerOut, JackHeartSubmitRequest, JHSymbolOut, VisibleSymbolOut
from app.services import jack_heart_service

router = APIRouter(prefix="/jack-heart", tags=["jack-heart"])


@router.get("/symbols", response_model=list[JHSymbolOut])
async def get_all_symbols(
    db: AsyncSession = Depends(get_db),
):
    """List all available card symbols in the game."""
    return await jack_heart_service.get_all_symbols(db)


@router.post(
    "/rounds/{round_id}/submit", response_model=JackHeartAnswerOut, status_code=status.HTTP_201_CREATED
)
async def submit_jack_heart_answer(
    round_id: uuid.UUID,
    payload: JackHeartSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await jack_heart_service.submit_answer(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
        submitted_symbol_id=payload.submitted_symbol_id,
    )


@router.get("/rounds/{round_id}/visible-symbols", response_model=list[VisibleSymbolOut])
async def get_visible_symbols(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Every *other* team's symbol for this round. The caller's own symbol
    must never appear here — see tests/test_jack_heart.py."""
    return await jack_heart_service.get_visible_symbols(
        db, round_id=round_id, current_team_id=current_team.team_id
    )


@router.get("/rooms/{room_id}/leaderboard", response_model=list)
async def get_jack_heart_room_leaderboard(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Leaderboard for Jack of Hearts within a specific room."""
    return await jack_heart_service.get_room_leaderboard(
        db, room_id=room_id, current_team_id=current_team.team_id
    )


@router.get("/rounds/{round_id}/my-suit")
async def get_my_suit(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Returns the caller's assigned suit and the card options for their suit."""
    return await jack_heart_service.get_team_suit_info(
        db, round_id=round_id, team_id=current_team.team_id
    )


