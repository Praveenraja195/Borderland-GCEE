import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.round import Room
from app.models.selection import Round1Selection, Suit
from app.models.team import Team
from app.schemas.selection import NumberAvailability, SelectionAvailabilityOut, SelectionCreate, SelectionOut
from app.services import selection_service

router = APIRouter(prefix="/rounds/{round_id}/selection", tags=["selection"])


@router.post("", response_model=SelectionOut, status_code=status.HTTP_201_CREATED)
async def create_selection(
    round_id: uuid.UUID,
    payload: SelectionCreate,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    return await selection_service.create_selection(
        db,
        round_id=round_id,
        team_id=current_team.team_id,
        suit_code=payload.suit_code,
        selected_number=payload.selected_number,
    )


@router.get("/me", response_model=SelectionOut)
async def get_my_selection(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    selection = await selection_service.get_my_selection(db, round_id=round_id, team_id=current_team.team_id)
    if selection is None:
        raise NotFoundError("No selection found for this team in this round")
    return selection


@router.get("/availability", response_model=SelectionAvailabilityOut)
async def get_selection_availability(
    round_id: uuid.UUID,
    suit_code: str,
    db: AsyncSession = Depends(get_db),
    _current_team: Team = Depends(get_current_team),
):
    """Audit Issue 5: lets a team see which numbers in a suit are still free
    before they pick, instead of finding out only after a 409 from a
    simultaneous same-suit same-number race."""
    suit = (await db.execute(select(Suit).where(Suit.code == suit_code.upper()))).scalar_one_or_none()
    if suit is None:
        raise NotFoundError(f"Unknown suit_code '{suit_code}'")

    taken_numbers = set(
        (
            await db.execute(
                select(Round1Selection.selected_number).where(
                    Round1Selection.round_id == round_id,
                    Round1Selection.suit_id == suit.suit_id,
                )
            )
        )
        .scalars()
        .all()
    )

    # Query actual room numbers for this round instead of hardcoding 1-10.
    # The fn_assign_room trigger maps selected_number -> room_number,
    # so we must only offer numbers that have a corresponding room.
    room_numbers = sorted(
        (
            await db.execute(
                select(Room.room_number).where(Room.round_id == round_id)
            )
        )
        .scalars()
        .all()
    )
    if not room_numbers:
        raise NotFoundError(
            "No rooms configured for this round yet. An admin must create rooms first."
        )

    return SelectionAvailabilityOut(
        suit_code=suit.code,
        numbers=[NumberAvailability(number=n, is_taken=n in taken_numbers) for n in room_numbers],
    )

