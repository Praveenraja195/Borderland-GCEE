import json
import logging
import uuid

logger = logging.getLogger("admin")

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.models.admin import Admin, AdminRole
from app.models.results import QualificationRule, RoomResult
from app.models.round import Room, Round
from app.models.team import Team
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
            (rd.status = 'COMPLETED' AND smm.is_published IS TRUE AND sas.is_published IS TRUE AND skd.is_published IS TRUE AND sjh.is_published IS TRUE) AS is_published,
            COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending
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


@router.get("/rounds/{round_id}/leaderboard", response_model=list[dict])
async def get_round_leaderboard_admin(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Live standings for every team in the round, in one query. Scores are
    the same ungated live values as /rooms/{room_id}/leaderboard (admins see
    scores before games are published; teams do not). Each row carries both
    `room_rank` (position inside its room) and `overall_rank` (across all
    rooms), so the console can show the by-room and overall views from a
    single fetch."""
    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    query = text("""
        WITH scored AS (
            SELECT
                t.team_id,
                t.team_code,
                t.team_name,
                st.code AS team_suit_code,
                st.symbol AS team_suit_symbol,
                r.room_id,
                r.room_code,
                r.room_number,
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
                CASE
                    WHEN rd.results_published_at IS NULL THEN NULL
                    WHEN rr.tiebreak_pending IS TRUE THEN NULL
                    ELSE COALESCE(rr.is_qualified, FALSE)
                END AS is_qualified,
                (rd.results_published_at IS NOT NULL) AS is_published,
                COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending
            FROM teams t
            JOIN round1_selections rs ON rs.team_id = t.team_id
            JOIN rooms r ON r.room_id = rs.room_id AND r.round_id = :round_id
            JOIN rounds rd ON rd.round_id = r.round_id
            LEFT JOIN suits st ON st.suit_id = rs.suit_id
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
        )
        SELECT
            team_id, team_code, team_name, team_suit_code, team_suit_symbol,
            room_id, room_code, room_number,
            mindmaze_score, ace_spade_score, king_diamond_score, jack_heart_score,
            (mindmaze_score + ace_spade_score + king_diamond_score + jack_heart_score)::FLOAT AS total_score,
            RANK() OVER (
                PARTITION BY room_id
                ORDER BY (mindmaze_score + ace_spade_score + king_diamond_score + jack_heart_score) DESC, team_code
            )::INT AS room_rank,
            RANK() OVER (
                ORDER BY (mindmaze_score + ace_spade_score + king_diamond_score + jack_heart_score) DESC, team_code
            )::INT AS overall_rank,
            is_qualified,
            is_published,
            tiebreak_pending
        FROM scored
        ORDER BY overall_rank, team_code;
    """)
    rows = (await db.execute(query, {"round_id": str(round_id)})).mappings().all()
    return [dict(row) for row in rows]


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


# Every SQL reader derives the broadcast id the same way so the value a team
# device echoes back in its ack matches what the delivery board expects.
BROADCAST_ID_SQL = "FLOOR(EXTRACT(EPOCH FROM results_published_at) * 1000)::BIGINT"


@router.post("/rounds/{round_id}/publish-leaderboard")
async def publish_round_leaderboard(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.SUPER_ADMIN)),
):
    """Publishes final results and Round 2 qualifications for every room in the
    round and broadcasts them to all team devices. Safe to call repeatedly:
    each call stamps a new rounds.results_published_at (the broadcast id), so
    every device replays its outcome and acknowledges again.

    Everything — closing open subrounds, publishing sessions, computing each
    room's results — happens in ONE transaction that only flips the round to
    published at the very end. Readers (the 3s team poll, the WS relay) can
    therefore never observe a published round whose room_results are missing,
    which used to make every team look eliminated for a moment."""
    from datetime import datetime, timezone

    from app.models.ace_spade import AceSpadeRound
    from app.models.game import GameSession, SessionStatus
    from app.models.jack_heart import JackHeartRound
    from app.models.king_diamond import KingDiamondRound
    from app.models.mindmaze import MindmazeRound
    from app.models.round import RoomStatus, Round, RoundStatus

    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    now = datetime.now(timezone.utc)

    sessions = (
        await db.execute(select(GameSession).where(GameSession.round_id == round_id))
    ).scalars().all()

    session_ids = [s.session_id for s in sessions]
    if session_ids:
        # Force-close whatever is still open. A MindMaze / Ace of Spades /
        # Jack of Hearts sub-round is "closed" once its deadline has passed
        # (see sessions.py); King of Diamonds also carries an explicit flag.
        # Never-started sub-rounds are closed too so the round is
        # unambiguously over; teams that never submitted simply score 0.
        for round_model in (MindmazeRound, AceSpadeRound, KingDiamondRound, JackHeartRound):
            await db.execute(
                update(round_model)
                .where(
                    round_model.session_id.in_(session_ids),
                    or_(round_model.deadline.is_(None), round_model.deadline > now),
                )
                .values(deadline=now, start_time=func.coalesce(round_model.start_time, now))
            )
        await db.execute(
            update(KingDiamondRound)
            .where(KingDiamondRound.session_id.in_(session_ids), KingDiamondRound.is_closed == False)
            .values(is_closed=True)
        )

    for s in sessions:
        s.is_published = True
        s.status = SessionStatus.COMPLETED

    rooms = (
        await db.execute(select(Room).where(Room.round_id == round_id))
    ).scalars().all()
    for r in rooms:
        r.status = RoomStatus.COMPLETED
    await db.flush()

    # Compute every room's scores, ranks and qualifications inside this same
    # transaction (commit=False), so they land together with the publish flag.
    for r in rooms:
        await results_service.recompute_room_results(db, room_id=r.room_id, commit=False)

    # A tie straddling the qualification cutoff holds just the tied teams and
    # opens a Death Card tiebreak for the room (see tiebreak_service).
    from app.services import tiebreak_service

    for r in rooms:
        await tiebreak_service.detect_and_create(db, room_id=r.room_id)

    round_obj.status = RoundStatus.COMPLETED
    if round_obj.end_time is None:
        round_obj.end_time = now
    round_obj.results_published_at = now
    await db.commit()

    broadcast_id = (
        await db.execute(
            text(f"SELECT {BROADCAST_ID_SQL} FROM rounds WHERE round_id = :round_id"),
            {"round_id": str(round_id)},
        )
    ).scalar()

    for r in rooms:
        await _publish(f"room:{r.room_id}:leaderboard")
        await _publish(f"room:{r.room_id}:sessions")
    await _publish("leaderboard:overall")
    await _publish(f"round:{round_id}:published")

    return {
        "round_id": str(round_id),
        "broadcast_id": int(broadcast_id) if broadcast_id is not None else None,
        "results_published_at": now.isoformat(),
        "rooms": len(rooms),
    }


@router.get("/rounds/{round_id}/team-connections")
async def get_round_team_connections(
    round_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_role(AdminRole.ROOM_ADMIN)),
):
    """Delivery board for the final-results broadcast: every team in the round
    grouped by room, whether its device is connected right now, and whether it
    has acknowledged the CURRENT broadcast. Acks are stored per broadcast id,
    so a re-send puts every device back to "sent, awaiting ack". Each ack also
    carries the outcome the device actually displayed, which is compared with
    the server's result for that team (is_verified)."""
    import redis.asyncio as redis
    from app.core.config import settings
    from app.models.round import Round

    round_obj = await db.get(Round, round_id)
    if round_obj is None:
        raise NotFoundError("Round not found")

    broadcast_id = (
        await db.execute(
            text(f"SELECT {BROADCAST_ID_SQL} FROM rounds WHERE round_id = :round_id"),
            {"round_id": str(round_id)},
        )
    ).scalar()
    broadcast_id = int(broadcast_id) if broadcast_id is not None else None
    is_published = broadcast_id is not None

    room_rows = (
        await db.execute(
            text("""
                SELECT room_id, room_code, room_number
                  FROM rooms
                 WHERE round_id = :round_id
                 ORDER BY room_number
            """),
            {"round_id": str(round_id)},
        )
    ).mappings().all()

    # Every team with a seat in one of this round's rooms, plus the outcome the
    # server will send it (only meaningful once published).
    team_rows = (
        await db.execute(
            text("""
                SELECT rm.room_id, t.team_id, t.team_code, t.team_name, rr.is_qualified,
                       COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending
                  FROM rooms rm
                  JOIN round1_selections rs ON rs.room_id = rm.room_id
                  JOIN teams t ON t.team_id = rs.team_id
                  LEFT JOIN room_results rr ON rr.room_id = rm.room_id AND rr.team_id = t.team_id
                 WHERE rm.round_id = :round_id
                 ORDER BY rm.room_number, t.team_code
            """),
            {"round_id": str(round_id)},
        )
    ).mappings().all()
    seated_ids = {row["team_id"] for row in team_rows}
    unassigned = [
        {"team_id": str(t.team_id), "team_code": t.team_code, "team_name": t.team_name}
        for t in (await db.execute(select(Team).order_by(Team.team_code))).scalars().all()
        if t.team_id not in seated_ids
    ]

    team_codes = [row["team_code"] for row in team_rows]
    online: dict[str, bool] = {}
    acks: dict[str, dict] = {}
    if team_codes:
        redis_client = redis.from_url(settings.redis_url)
        try:
            pipe = redis_client.pipeline()
            for code in team_codes:
                pipe.exists(f"team:online:{code}")
            if is_published:
                pipe.hgetall(f"round:{round_id}:results_ack:{broadcast_id}")
            res = await pipe.execute()
            online = {code: bool(res[i]) for i, code in enumerate(team_codes)}
            if is_published:
                raw = res[len(team_codes)] or {}
                for k, v in raw.items():
                    code = k.decode() if isinstance(k, bytes) else k
                    try:
                        acks[code] = json.loads(v.decode() if isinstance(v, bytes) else v)
                    except Exception:
                        acks[code] = {"at": None, "outcome": None}
        except Exception:
            logger.exception("Failed to query Redis for team connections")
        finally:
            await redis_client.close()

    rooms_out = {
        str(row["room_id"]): {
            "room_id": str(row["room_id"]),
            "room_code": row["room_code"],
            "room_number": row["room_number"],
            "team_count": 0,
            "connected_count": 0,
            "acknowledged_count": 0,
            "teams": [],
        }
        for row in room_rows
    }
    total_connected = 0
    total_acked = 0
    for row in team_rows:
        code = row["team_code"]
        expected = None
        if is_published:
            if row["tiebreak_pending"]:
                expected = "TIEBREAK"
            else:
                expected = "QUALIFIED" if row["is_qualified"] else "ELIMINATED"
        ack = acks.get(code)
        is_connected = bool(online.get(code))
        is_acked = ack is not None
        acked_outcome = ack.get("outcome") if ack else None
        is_verified = is_acked and (acked_outcome is None or acked_outcome == expected)
        room = rooms_out[str(row["room_id"])]
        room["teams"].append(
            {
                "team_id": str(row["team_id"]),
                "team_code": code,
                "team_name": row["team_name"],
                "is_connected": is_connected,
                "is_acknowledged": is_acked,
                "acknowledged_at": ack.get("at") if ack else None,
                "expected_outcome": expected,
                "acked_outcome": acked_outcome,
                "is_verified": is_verified,
            }
        )
        room["team_count"] += 1
        if is_connected:
            room["connected_count"] += 1
            total_connected += 1
        if is_acked:
            room["acknowledged_count"] += 1
            total_acked += 1

    return {
        "round_id": str(round_id),
        "is_published": is_published,
        "broadcast_id": broadcast_id,
        "results_published_at": round_obj.results_published_at.isoformat()
        if round_obj.results_published_at
        else None,
        "total_teams": len(team_rows),
        "connected_count": total_connected,
        "acknowledged_count": total_acked,
        "rooms": list(rooms_out.values()),
        "unassigned_teams": unassigned,
    }


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
