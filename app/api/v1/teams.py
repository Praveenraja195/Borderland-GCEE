import uuid
from fastapi import APIRouter, Depends
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team, get_db
from app.models.team import Team
from app.models.selection import Round1Selection
from app.models.game import GameSession, TeamViewAck
from app.schemas.team import TeamOut
from app.workers import jobs

router = APIRouter(prefix="/teams", tags=["teams"])


# Audit Issue 4: team registration used to live here (POST /teams) with no
# auth guard, so anyone on the network could exhaust the 40-team cap or
# pre-register fake teams. Registration now lives exclusively at
# POST /api/v1/admin/teams (SUPER_ADMIN only) — see app/api/v1/admin.py.


@router.get("/me", response_model=TeamOut)
async def get_my_team(current_team: Team = Depends(get_current_team)):
    return current_team


@router.post("/view-published-results")
async def acknowledge_all_published_views(
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Automatically records view acknowledgements for all published game sessions
    in the team's assigned room."""
    selections = (
        await db.execute(
            select(Round1Selection).where(Round1Selection.team_id == current_team.team_id)
        )
    ).scalars().all()
    room_ids = [s.room_id for s in selections if s.room_id]

    # Find all sessions in team's rooms or where team is in roster
    all_sessions = (
        await db.execute(select(GameSession).where(GameSession.is_published == True))
    ).scalars().all()

    ack_count = 0
    for sess in all_sessions:
        is_in_room = sess.room_id in room_ids
        is_in_roster = sess.roster_team_ids and any(str(current_team.team_id) == str(x) for x in sess.roster_team_ids)
        if is_in_room or is_in_roster or not sess.roster_team_ids:
            existing = (
                await db.execute(
                    select(TeamViewAck).where(
                        TeamViewAck.session_id == sess.session_id,
                        TeamViewAck.team_id == current_team.team_id,
                        TeamViewAck.view_type == "PUBLISHED_RESULTS",
                        TeamViewAck.round_id.is_(None),
                    )
                )
            ).scalars().first()

            if not existing:
                ack = TeamViewAck(
                    session_id=sess.session_id,
                    team_id=current_team.team_id,
                    view_type="PUBLISHED_RESULTS",
                    round_id=None,
                )
                db.add(ack)
                ack_count += 1

    if ack_count > 0:
        await db.commit()
        for r_id in room_ids:
            await jobs._publish(f"room:{r_id}:sessions")

    return {"acknowledged": ack_count}
