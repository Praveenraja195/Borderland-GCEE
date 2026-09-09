import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.models.round import Round, RoundStatus
from app.models.selection import Round1Selection, Suit


async def create_selection(
    db: AsyncSession,
    *,
    round_id: uuid.UUID,
    team_id: uuid.UUID,
    suit_code: str,
    selected_number: int,
) -> Round1Selection:
    """Insert a team's one-time suit+number selection.

    Business rule check here is limited to "is the round ACTIVE?" — the DB
    (UNIQUE(round_id, team_id) + trg_assign_room) is the source of truth for
    "has this team already selected" and "what room does this map to". We
    deliberately do NOT pre-check for an existing selection: attempt the
    insert and let the IntegrityError -> 409 mapping in app.core.exceptions
    do the real work.
    """
    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")
    if round_obj.status != RoundStatus.ACTIVE:
        raise ConflictError("Selection is only open while the round is ACTIVE")

    suit = (await db.execute(select(Suit).where(Suit.code == suit_code))).scalar_one_or_none()
    if suit is None:
        raise NotFoundError(f"Unknown suit_code '{suit_code}'")

    selection = Round1Selection(
        round_id=round_id,
        team_id=team_id,
        suit_id=suit.suit_id,
        selected_number=selected_number,
    )
    db.add(selection)
    # flush (not commit) so trg_assign_room / UNIQUE constraints fire and any
    # IntegrityError surfaces here, inside the request's single transaction.
    await db.flush()
    await db.commit()
    await db.refresh(selection)
    return selection


async def get_my_selection(
    db: AsyncSession, *, round_id: uuid.UUID, team_id: uuid.UUID
) -> Round1Selection | None:
    result = await db.execute(
        select(Round1Selection).where(
            Round1Selection.round_id == round_id,
            Round1Selection.team_id == team_id,
        )
    )
    return result.scalar_one_or_none()
