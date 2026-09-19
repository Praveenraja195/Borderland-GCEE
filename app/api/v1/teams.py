import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
import redis.asyncio as redis
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team, get_db
from app.core.config import settings
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


@router.post("/heartbeat")
async def team_heartbeat(
    current_team: Team = Depends(get_current_team),
):
    """Refreshes team presence in Redis so admin broadcast accurately tracks connected devices."""
    try:
        r = redis.from_url(settings.redis_url)
        pipe = r.pipeline()
        pipe.set(f"team:online:{current_team.team_code}", "1", ex=15)
        pipe.sadd("active_online_teams", current_team.team_code)
        await pipe.execute()
        await r.close()
    except Exception:
        pass
    return {"status": "ok", "team_code": current_team.team_code}


from pydantic import BaseModel
from app.models.round import Round, RoundStatus


class AckPublishedResultsPayload(BaseModel):
    round_id: uuid.UUID | None = None
    # Which broadcast the device just rendered (results_broadcast_id from the
    # leaderboard payload) and what it showed, so the admin delivery board can
    # verify the team saw the right outcome for THIS send.
    broadcast_id: int | None = None
    outcome: str | None = None  # "QUALIFIED" | "ELIMINATED"


@router.post("/view-published-results")
async def acknowledge_all_published_views(
    payload: AckPublishedResultsPayload | None = None,
    db: AsyncSession = Depends(get_db),
    current_team: Team = Depends(get_current_team),
):
    """Records that this device has displayed the published final results.

    Writes the durable TeamViewAck rows for the published sessions in the
    team's room, and — when the device says which broadcast it rendered — a
    per-broadcast ack in Redis that the admin delivery board reads. A device
    only calls this after it has actually shown its outcome, so an ack means
    "seen", not merely "online"."""
    selections = (
        await db.execute(
            select(Round1Selection).where(Round1Selection.team_id == current_team.team_id)
        )
    ).scalars().all()
    room_ids = [s.room_id for s in selections if s.room_id]
    round_ids = list({s.round_id for s in selections if s.round_id})
    if payload and payload.round_id and payload.round_id not in round_ids:
        round_ids.append(payload.round_id)

    if not round_ids:
        active_r_ids = (
            await db.execute(
                select(Round.round_id).where(
                    Round.status.in_([RoundStatus.ACTIVE, RoundStatus.COMPLETED])
                )
            )
        ).scalars().all()
        round_ids = list(set(active_r_ids))

    now_iso = datetime.now(timezone.utc).isoformat()

    # Find all sessions in team's rooms or where team is in roster
    all_sessions = (
        await db.execute(select(GameSession).where(GameSession.is_published == True))
    ).scalars().all()

    ack_count = 0
    for sess in all_sessions:
        is_in_room = sess.room_id in room_ids
        is_in_roster = sess.roster_team_ids and any(str(current_team.team_id) == str(x) for x in sess.roster_team_ids)
        if is_in_room or is_in_roster:
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

    # Per-broadcast ack for the admin delivery board. Keyed by broadcast id so a
    # re-send starts every team back at "awaiting ack".
    broadcast_id = payload.broadcast_id if payload else None
    if broadcast_id is not None:
        try:
            r = redis.from_url(settings.redis_url)
            pipe = r.pipeline()
            record = json.dumps({"at": now_iso, "outcome": payload.outcome})
            for r_id in round_ids:
                key = f"round:{r_id}:results_ack:{broadcast_id}"
                pipe.hset(key, current_team.team_code, record)
                pipe.expire(key, 7 * 24 * 3600)
                pipe.publish(
                    f"round:{r_id}:acks",
                    json.dumps(
                        {
                            "team_code": current_team.team_code,
                            "broadcast_id": broadcast_id,
                            "outcome": payload.outcome,
                            "acknowledged_at": now_iso,
                        }
                    ),
                )
            await pipe.execute()
            await r.close()
        except Exception:
            pass

    return {
        "acknowledged": ack_count,
        "team_code": current_team.team_code,
        "broadcast_id": broadcast_id,
        "acknowledged_at": now_iso,
    }
