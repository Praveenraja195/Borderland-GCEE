"""
Fix §4: shared submission authorization helper extracted from the three
near-identical copy-pasted blocks in mindmaze_service, king_diamond_service,
and jack_heart_service. A future change to this guard (deadline logic,
room-binding check, etc.) only needs to land here.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError
from app.models.game import GameSession, SessionStatus
from app.models.selection import Round1Selection


async def authorize_game_submission(
    db: AsyncSession,
    *,
    round_obj,           # MindmazeRound | KingDiamondRound | JackHeartRound
    team_id: uuid.UUID,
    check_deadline: bool = True,
) -> GameSession:
    """
    Validates that a team may submit for `round_obj` right now:
      1. Deadline has not passed (with 30s grace period if check_deadline=True).
      2. The session is not PAUSED.
      3. The team's Round 1 selection places them in the room that owns this
         session (room-binding check, Audit Issue 6).

    Returns the GameSession on success; raises ConflictError or ForbiddenError
    on failure.
    """
    if check_deadline:
        deadline = getattr(round_obj, "deadline", None)
        if deadline and datetime.now(timezone.utc) > (deadline + timedelta(seconds=30)):
            raise ConflictError("Submission deadline has passed")

    session = await db.get(GameSession, round_obj.session_id)
    if session is not None and session.status == SessionStatus.PAUSED:
        raise ConflictError("This session is paused by an admin")

    if session is None:
        raise ForbiddenError("No active session found for this round")

    selection = (
        await db.execute(
            select(Round1Selection).where(
                Round1Selection.team_id == team_id,
                Round1Selection.round_id == session.round_id,
            )
        )
    ).scalar_one_or_none()
    if selection is None or selection.room_id != session.room_id:
        raise ForbiddenError("Your team is not assigned to this room")

    return session
