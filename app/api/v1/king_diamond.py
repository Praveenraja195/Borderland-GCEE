import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.db.session import get_db
from app.models.team import Team
from app.schemas.king_diamond import (
    KingDiamondRoundResultOut,
    KingDiamondSubmissionOut,
    KingDiamondSubmitRequest,
)
from app.services import king_diamond_service

router = APIRouter(prefix="/king-diamond", tags=["king-diamond"])


@router.post(
    "/rounds/{round_id}/submit",
    response_model=KingDiamondSubmissionOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit_king_diamond_number(
    round_id: uuid.UUID,
    payload: KingDiamondSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Duplicate submit -> IntegrityError on UNIQUE(round_id, team_id) -> 409
    (handled centrally in app.core.exceptions). Audit §2.3: submit_number now
    rejects a late submission with 409 (matching MindMaze/Jack of Hearts)
    instead of silently accepting it with is_valid=false — see the comment
    in king_diamond_service.submit_number for the reasoning.

    Fix: the orphaned POST /king-diamond/rounds/{id}/close endpoint has been
    removed. It duplicated admin_games.py force_close_king_diamond_round but
    skipped _maybe_close_session(), leaving sessions in a half-closed state.
    Use POST /admin/king-diamond/rounds/{id}/force-close instead."""
    return await king_diamond_service.submit_number(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
        submitted_number=payload.submitted_number,
    )


@router.get("/rounds/{round_id}/result", response_model=KingDiamondRoundResultOut)
async def get_king_diamond_round_result(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Aug 2026: backs the team app's post-submit computation reveal —
    average/target/own-rank/points, polled after auto-submit until the
    sub-round actually closes (is_closed flips true once the scheduled
    close job or an admin force-close finishes computing it)."""
    return await king_diamond_service.get_team_round_result(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
    )


@router.get("/rooms/{room_id}/leaderboard", response_model=list)
async def get_king_diamond_room_leaderboard(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await king_diamond_service.get_room_leaderboard(
        db,
        room_id=room_id,
        current_team_id=current_team.team_id,
    )

