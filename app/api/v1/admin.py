import logging
import uuid

logger = logging.getLogger("admin")

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.admin import Admin, AdminRole
from app.models.results import QualificationRule, RoomResult
from app.models.round import Room
from app.schemas.admin import (
    AdminAccountCreate,
    AdminAccountOut,
    AdminPasswordReset,
    AdminRoomAssign,
    QualificationRuleOut,
    QualificationRuleUpsert,
)
from app.schemas.team import TeamAdminDetailOut, TeamAdminListEntry, TeamCreate, TeamOut, TeamPasswordReset
from app.services import admin_service, results_service
from app.workers.jobs import _publish

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# §2.1 Team Management
# ---------------------------------------------------------------------------


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def admin_create_team(
    payload: TeamCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Audit Issue 4: registration moved here from the public, unauthenticated
    POST /api/v1/teams endpoint."""
    return await admin_service.create_team(
        db, team_code=payload.team_code, team_name=payload.team_name, password=payload.password
    )


@router.get("/teams", response_model=list[TeamAdminListEntry])
async def admin_list_teams(
    round_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    return await admin_service.list_teams(db, round_id=round_id)


@router.get("/teams/{team_id}", response_model=TeamAdminDetailOut)
async def admin_get_team(
    team_id: uuid.UUID,
    round_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    return await admin_service.get_team_detail(db, team_id=team_id, round_id=round_id)


@router.patch("/teams/{team_id}/password", response_model=TeamOut)
async def admin_reset_team_password(
    team_id: uuid.UUID,
    payload: TeamPasswordReset,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.reset_team_password(db, team_id=team_id, new_password=payload.new_password)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_team(
    team_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    await admin_service.delete_team(db, team_id=team_id)


# ---------------------------------------------------------------------------
# §2.7 Score & Leaderboard Management
# ---------------------------------------------------------------------------


@router.post("/rooms/{room_id}/recompute-results", status_code=status.HTTP_204_NO_CONTENT)
async def recompute_room_results(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    # Audit Issue 10: ROOM_ADMIN checked role only, with no binding between
    # an admin and the room they actually manage, so any ROOM_ADMIN could
    # recompute any room. Tightened to SUPER_ADMIN only.
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Manually re-runs fn_compute_room_results(room_id) — an escape hatch
    if a score needed correcting after the fact."""
    await results_service.recompute_room_results(db, room_id=room_id)


@router.get("/rooms/{room_id}/results", response_model=list[dict])
async def get_room_results(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    from app.models.team import Team
    rows = (
        await db.execute(
            select(RoomResult, Team.team_code, Team.team_name)
            .join(Team, Team.team_id == RoomResult.team_id)
            .where(RoomResult.room_id == room_id)
            .order_by(RoomResult.rank)
        )
    ).all()
    return [
        {
            "team_id": r.RoomResult.team_id,
            "team_code": r.team_code,
            "team_name": r.team_name,
            "mindmaze_score": r.RoomResult.mindmaze_score,
            "king_diamond_score": r.RoomResult.king_diamond_score,
            "jack_heart_score": r.RoomResult.jack_heart_score,
            "total_score": r.RoomResult.total_score,
            "rank": r.RoomResult.rank,
            "is_qualified": r.RoomResult.is_qualified,
        }
        for r in rows
    ]


@router.get("/rooms/{room_id}/leaderboard", response_model=list[dict])
async def get_room_leaderboard_admin(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Live leaderboard from game_scores — same query the WebSocket broadcasts.
    Unlike /results (which reads the precomputed room_results table and is only
    populated after room COMPLETED), this always returns current live scores."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    query = text("""
        SELECT
            t.team_id,
            r.room_id,
            r.room_code,
            t.team_code,
            t.team_name,
            st.code AS team_suit_code,
            st.symbol AS team_suit_symbol,
            COALESCE(mm.score, (
                SELECT COALESCE(SUM(mr.round_score), 0)
                FROM mindmaze_results mr
                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
            ), 0)::FLOAT AS mindmaze_score,
            COALESCE(as_.score, (
                SELECT COALESCE(SUM(asr.round_score), 0)
                FROM ace_spade_results asr
                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
            ), 0)::FLOAT AS ace_spade_score,
            COALESCE(kd.score, (
                SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 0.0)::FLOAT AS king_diamond_score,
            COALESCE(jh.score, (
                SELECT COALESCE(SUM(jha.round_score), 0)
                FROM jack_heart_answers jha
                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
            ), 0)::FLOAT AS jack_heart_score,
            (COALESCE(mm.score, (
                SELECT COALESCE(SUM(mr.round_score), 0)
                FROM mindmaze_results mr
                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
            ), 0) + COALESCE(as_.score, (
                SELECT COALESCE(SUM(asr.round_score), 0)
                FROM ace_spade_results asr
                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
            ), 0) + COALESCE(kd.score, (
                SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 0.0) + COALESCE(jh.score, (
                SELECT COALESCE(SUM(jha.round_score), 0)
                FROM jack_heart_answers jha
                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
            ), 0))::FLOAT AS total_score,
            RANK() OVER (
                PARTITION BY r.room_id
                ORDER BY (COALESCE(mm.score, (
                    SELECT COALESCE(SUM(mr.round_score), 0)
                    FROM mindmaze_results mr
                    JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                    WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                ), 0) + COALESCE(as_.score, (
                    SELECT COALESCE(SUM(asr.round_score), 0)
                    FROM ace_spade_results asr
                    JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                    WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                ), 0) + COALESCE(kd.score, (
                    SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                    FROM king_diamond_submissions kds
                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                ), 0.0) + COALESCE(jh.score, (
                    SELECT COALESCE(SUM(jha.round_score), 0)
                    FROM jack_heart_answers jha
                    JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                    WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                ), 0)) DESC, t.team_code
            )::INT AS live_rank,
            CASE
                WHEN (rd.status = 'COMPLETED' AND smm.is_published IS TRUE AND sas.is_published IS TRUE AND skd.is_published IS TRUE AND sjh.is_published IS TRUE) THEN
                    COALESCE(rr.is_qualified, FALSE)
                ELSE NULL
            END AS is_qualified,
            (rd.status = 'COMPLETED' AND smm.is_published IS TRUE AND sas.is_published IS TRUE AND skd.is_published IS TRUE AND sjh.is_published IS TRUE) AS is_published
        FROM teams t
        JOIN round1_selections rs ON rs.team_id = t.team_id AND rs.room_id = :room_id
        LEFT JOIN suits st ON st.suit_id = rs.suit_id
        JOIN rooms r ON r.room_id = rs.room_id
        JOIN rounds rd ON rd.round_id = r.round_id
        LEFT JOIN game_sessions smm ON smm.room_id = r.room_id
               AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
        LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
        LEFT JOIN game_sessions sas ON sas.room_id = r.room_id
               AND sas.game_id = (SELECT game_id FROM games WHERE code = 'ACE_SPADE')
        LEFT JOIN game_scores as_ ON as_.session_id = sas.session_id AND as_.team_id = t.team_id
        LEFT JOIN game_sessions skd ON skd.room_id = r.room_id
               AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
        LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
        LEFT JOIN game_sessions sjh ON sjh.room_id = r.room_id
               AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
        LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
        LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id
        ORDER BY live_rank;
    """)
    rows = (await db.execute(query, {"room_id": str(room_id)})).mappings().all()

    # Query round-by-round details for each game in this room
    mm_q = text("""
        SELECT 
            mr.team_id,
            mrd.round_number,
            mr.moves,
            mr.mistakes,
            mr.correct_tiles,
            mr.round_score::FLOAT as score,
            mr.completion_time
        FROM mindmaze_results mr
        JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
        JOIN game_sessions gs ON gs.session_id = mrd.session_id
        WHERE gs.room_id = :room_id
        ORDER BY mrd.round_number ASC
    """)
    as_q = text("""
        SELECT 
            asr.team_id,
            asrd.round_number,
            asr.moves,
            asr.wrong_picks,
            asr.correct_picks,
            asr.round_score::FLOAT as score,
            asr.completion_time
        FROM ace_spade_results asr
        JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
        JOIN game_sessions gs ON gs.session_id = asrd.session_id
        WHERE gs.room_id = :room_id
        ORDER BY asrd.round_number ASC
    """)
    kd_q = text("""
        SELECT 
            kds.team_id,
            kdr.round_number,
            kds.submitted_number::FLOAT as submitted_number,
            kdr.target_value::FLOAT as target_value,
            kdr.average_value::FLOAT as average_value,
            kds.difference::FLOAT as difference,
            kds.rank,
            kds.round_score::FLOAT as penalty,
            GREATEST(0.0, 20.0 - COALESCE(kds.round_score, 0.0))::FLOAT as score,
            kds.is_winner,
            kdr.is_closed
        FROM king_diamond_submissions kds
        JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
        JOIN game_sessions gs ON gs.session_id = kdr.session_id
        WHERE gs.room_id = :room_id
        ORDER BY kdr.round_number ASC
    """)
    jh_q = text("""
        SELECT 
            jha.team_id,
            jhr.round_number,
            jha.is_correct,
            jha.round_score::FLOAT as score,
            s_sub.label as submitted_symbol,
            s_act.label as actual_symbol,
            jha.time_taken
        FROM jack_heart_answers jha
        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
        JOIN game_sessions gs ON gs.session_id = jhr.session_id
        LEFT JOIN jh_symbols s_sub ON s_sub.symbol_id = jha.submitted_symbol_id
        LEFT JOIN jh_symbols s_act ON s_act.symbol_id = jha.actual_symbol_id
        WHERE gs.room_id = :room_id
        ORDER BY jhr.round_number ASC
    """)

    params = {"room_id": str(room_id)}
    mm_res = (await db.execute(mm_q, params)).mappings().all()
    as_res = (await db.execute(as_q, params)).mappings().all()
    kd_res = (await db.execute(kd_q, params)).mappings().all()
    jh_res = (await db.execute(jh_q, params)).mappings().all()

    def _fmt_td(td):
        if td is None:
            return None
        total_sec = td.total_seconds()
        return f"{int(total_sec // 60):02d}:{int(total_sec % 60):02d}"

    # Group rounds by team_id
    team_rounds: dict[uuid.UUID, dict[str, list[dict]]] = {}
    for r in mm_res:
        t_id = r["team_id"]
        team_rounds.setdefault(t_id, {}).setdefault("MINDMAZE", []).append({
            "round_number": r["round_number"],
            "moves": r["moves"],
            "mistakes": r["mistakes"],
            "correct_tiles": r["correct_tiles"],
            "score": r["score"],
            "completion_time": _fmt_td(r["completion_time"]),
        })

    for r in as_res:
        t_id = r["team_id"]
        team_rounds.setdefault(t_id, {}).setdefault("ACE_SPADE", []).append({
            "round_number": r["round_number"],
            "moves": r["moves"],
            "wrong_picks": r["wrong_picks"],
            "correct_picks": r["correct_picks"],
            "score": r["score"],
            "completion_time": _fmt_td(r["completion_time"]),
        })

    for r in kd_res:
        t_id = r["team_id"]
        team_rounds.setdefault(t_id, {}).setdefault("KING_DIAMOND", []).append({
            "round_number": r["round_number"],
            "submitted_number": r["submitted_number"],
            "target_value": r["target_value"],
            "average_value": r["average_value"],
            "difference": r["difference"],
            "rank": r["rank"],
            "penalty": r["penalty"],
            "score": r["score"],
            "is_winner": r["is_winner"],
            "is_closed": r["is_closed"],
        })

    for r in jh_res:
        t_id = r["team_id"]
        team_rounds.setdefault(t_id, {}).setdefault("JACK_HEART", []).append({
            "round_number": r["round_number"],
            "is_correct": r["is_correct"],
            "score": r["score"],
            "submitted_symbol": r["submitted_symbol"],
            "actual_symbol": r["actual_symbol"],
            "time_taken": _fmt_td(r["time_taken"]),
        })

    results = []
    for row in rows:
        d = dict(row)
        t_id = d.get("team_id")
        d["round_details"] = team_rounds.get(t_id, {
            "MINDMAZE": [],
            "ACE_SPADE": [],
            "KING_DIAMOND": [],
            "JACK_HEART": [],
        })
        results.append(d)

    return results


@router.put("/rounds/{round_id}/qualification-rule", response_model=QualificationRuleOut)
async def upsert_qualification_rule(
    round_id: uuid.UUID,
    payload: QualificationRuleUpsert,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    existing = (
        await db.execute(
            select(QualificationRule).where(
                QualificationRule.round_id == round_id, QualificationRule.room_id == payload.room_id
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.top_n = payload.top_n
        rule = existing
    else:
        rule = QualificationRule(round_id=round_id, room_id=payload.room_id, top_n=payload.top_n)
        db.add(rule)

    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/rounds/{round_id}/qualification-rules", response_model=list[QualificationRuleOut])
async def list_qualification_rules(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    rules = (
        await db.execute(select(QualificationRule).where(QualificationRule.round_id == round_id))
    ).scalars().all()
    return rules


@router.post("/rooms/{room_id}/publish-leaderboard", status_code=status.HTTP_204_NO_CONTENT)
async def publish_leaderboard(
    room_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Manually publishes "updated" to the Redis channels the WebSocket
    layer relays, forcing connected clients to refresh without waiting for
    the next roll-up job, and marks sessions in this room as published and completed."""
    room = await db.get(Room, room_id)
    if room is None:
        raise NotFoundError("Room not found")

    from app.models.game import GameSession, SessionStatus
    from app.models.round import RoomStatus

    room.status = RoomStatus.COMPLETED

    sessions = (
        await db.execute(select(GameSession).where(GameSession.room_id == room_id))
    ).scalars().all()
    for s in sessions:
        s.is_published = True
        s.status = SessionStatus.COMPLETED
    await db.commit()

    try:
        await results_service.recompute_room_results(db, room_id=room_id)
    except Exception:
        logger.exception("Failed to recompute results for room %s", room_id)

    await _publish(f"room:{room_id}:leaderboard")
    await _publish(f"room:{room_id}:sessions")
    await _publish("leaderboard:overall")


@router.post("/rounds/{round_id}/publish-leaderboard", status_code=status.HTTP_204_NO_CONTENT)
async def publish_round_leaderboard(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Publishes leaderboard and Round 2 qualification results for all rooms within a round at once.
    Marks the round as COMPLETED, publishes all sessions, computes qualifications, and broadcasts."""
    from app.models.game import GameSession, SessionStatus
    from app.models.round import RoomStatus, Round, RoundStatus
    from sqlalchemy import text

    round_obj = await db.get(Round, round_id)
    if round_obj is not None:
        round_obj.status = RoundStatus.COMPLETED

    sessions = (
        await db.execute(select(GameSession).where(GameSession.round_id == round_id))
    ).scalars().all()
    for s in sessions:
        s.is_published = True
        s.status = SessionStatus.COMPLETED

    rooms = (
        await db.execute(select(Room).where(Room.round_id == round_id))
    ).scalars().all()
    for r in rooms:
        r.status = RoomStatus.COMPLETED

    await db.commit()

    for r in rooms:
        try:
            await results_service.recompute_room_results(db, room_id=r.room_id)
        except Exception:
            logger.exception("Failed to recompute results for room %s", r.room_id)
            try:
                await db.execute(text("SELECT fn_compute_room_results(:room_id)"), {"room_id": str(r.room_id)})
                await db.commit()
            except Exception:
                pass

    for r in rooms:
        await _publish(f"room:{r.room_id}:leaderboard")
        await _publish(f"room:{r.room_id}:sessions")
    await _publish("leaderboard:overall")


# ---------------------------------------------------------------------------
# §2.9 Admin Account Management
# ---------------------------------------------------------------------------


@router.post("/admins", response_model=AdminAccountOut, status_code=status.HTTP_201_CREATED)
async def create_admin_account(
    payload: AdminAccountCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.create_admin(
        db, username=payload.username, password=payload.password, role=payload.role
    )


@router.get("/admins", response_model=list[AdminAccountOut])
async def list_admin_accounts(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.list_admins(db)


@router.patch("/admins/{admin_id}/password", response_model=AdminAccountOut)
async def reset_admin_password(
    admin_id: uuid.UUID,
    payload: AdminPasswordReset,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    return await admin_service.reset_admin_password(db, admin_id=admin_id, new_password=payload.new_password)


@router.patch("/admins/{admin_id}/room", response_model=AdminAccountOut)
async def assign_admin_room(
    admin_id: uuid.UUID,
    payload: AdminRoomAssign,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """§2.9: bind a ROOM_ADMIN to the one room they manage (or pass
    room_id: null to unbind them back to unrestricted, e.g. before
    reassigning). Only meaningful for ROOM_ADMIN accounts; harmless no-op
    boundary-wise for SUPER_ADMIN, which is always unrestricted."""
    return await admin_service.assign_admin_room(db, admin_id=admin_id, room_id=payload.room_id)


@router.delete("/admins/{admin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_admin_account(
    admin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: Admin = Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    await admin_service.deactivate_admin(db, admin_id=admin_id, current_admin_id=current_admin.admin_id)
