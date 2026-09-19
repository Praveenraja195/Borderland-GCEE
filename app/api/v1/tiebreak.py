"""Death Card tiebreaker endpoints.

Admin (console) — list the round's tiebreaks, start / advance / reset one.
Team (device)   — read my tiebreak state, claim a card.

Every read runs tiebreak_service.tick() first, which resolves an expired
round and deals the next one after the reveal pause. Devices poll every
second while the screen is up, so the game advances on its own once the
admin starts it — no scheduler job involved.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team, require_role
from app.core.exceptions import ConflictError, NotFoundError
from app.db.session import get_db
from app.models.admin import AdminRole
from app.models.team import Team
from app.services import tiebreak_service

router = APIRouter(prefix="/tiebreak", tags=["tiebreak"])


async def _tick_and_commit(db: AsyncSession, session) -> None:
    """Advance the lazy state machine; a lost race on the next-round unique
    key just means another request already dealt it."""
    try:
        if await tiebreak_service.tick(db, session):
            await db.commit()
            await tiebreak_service.publish_room(session.room_id)
    except IntegrityError:
        await db.rollback()
    await db.refresh(session)


# ---------------------------------------------------------------- admin

@router.get("/admin/rounds/{round_id}")
async def admin_list_tiebreaks(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    sessions = await tiebreak_service.sessions_for_round(db, round_id)
    for s in sessions:
        await _tick_and_commit(db, s)
    return [await tiebreak_service.serialize(db, s) for s in sessions]


@router.post("/admin/sessions/{session_id}/start")
async def admin_start(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    session = await tiebreak_service.get_session(db, session_id)
    await tiebreak_service.start(db, session)
    await db.commit()
    await tiebreak_service.publish_room(session.room_id)
    return await tiebreak_service.serialize(db, session)


@router.post("/admin/sessions/{session_id}/advance")
async def admin_advance(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Start if pending, reveal the open round now, or deal the next round now."""
    session = await tiebreak_service.get_session(db, session_id)
    try:
        await tiebreak_service.advance(db, session)
        await db.commit()
    except IntegrityError:
        await db.rollback()
    await tiebreak_service.publish_room(session.room_id)
    await db.refresh(session)
    return await tiebreak_service.serialize(db, session)


@router.post("/admin/sessions/{session_id}/reset")
async def admin_reset(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    session = await tiebreak_service.get_session(db, session_id)
    await tiebreak_service.reset(db, session)
    await db.commit()
    await tiebreak_service.publish_room(session.room_id)
    return await tiebreak_service.serialize(db, session)


# ----------------------------------------------------------------- team

class PickPayload(BaseModel):
    card_index: int = Field(ge=0, le=64)


@router.get("/me")
async def my_tiebreak(
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """The tiebreak this team is part of, or null."""
    session = await tiebreak_service.session_for_team(db, current_team.team_id)
    if session is None:
        return None
    await _tick_and_commit(db, session)
    return await tiebreak_service.serialize(db, session, for_team_id=current_team.team_id)


@router.post("/me/pick")
async def my_pick(
    payload: PickPayload,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    session = await tiebreak_service.session_for_team(db, current_team.team_id)
    if session is None:
        raise NotFoundError("You are not in a tiebreak")
    await _tick_and_commit(db, session)
    try:
        await tiebreak_service.pick(db, session, current_team.team_id, payload.card_index)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("That card is already taken")
    return await tiebreak_service.serialize(db, session, for_team_id=current_team.team_id)
