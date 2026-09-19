import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_team
from app.db.session import get_db
from app.schemas.leaderboard import GameLeaderboardEntry, OverallLeaderboardEntry, RoomLeaderboardEntry

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])
rooms_router = APIRouter(prefix="/rooms", tags=["leaderboard"])


@rooms_router.get("/{room_id}/leaderboard", response_model=list[RoomLeaderboardEntry])
async def get_room_leaderboard(
    room_id: uuid.UUID, db: AsyncSession = Depends(get_db), _current_team=Depends(get_current_team)
):
    query = text("""
        SELECT
            r.room_id,
            r.room_code,
            t.team_code,
            t.team_name,
            st.code AS team_suit_code,
            st.symbol AS team_suit_symbol,
            CASE
                WHEN smm.is_published IS TRUE THEN
                    COALESCE(mm.score, (
                        SELECT COALESCE(SUM(mr.round_score), 0)
                        FROM mindmaze_results mr
                        JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                        WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS mindmaze_score,
            CASE
                WHEN sas.is_published IS TRUE THEN
                    COALESCE(as_.score, (
                        SELECT COALESCE(SUM(asr.round_score), 0)
                        FROM ace_spade_results asr
                        JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                        WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS ace_spade_score,
            CASE
                WHEN skd.is_published IS TRUE THEN
                    COALESCE(kd.score, GREATEST(0.0,
                        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                        - COALESCE((
                            SELECT SUM(kds.round_score)
                            FROM king_diamond_submissions kds
                            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                        ), 0.0)
                    ))::FLOAT
                ELSE NULL
            END AS king_diamond_score,
            CASE
                WHEN sjh.is_published IS TRUE THEN
                    COALESCE(jh.score, (
                        SELECT COALESCE(SUM(jha.round_score), 0)
                        FROM jack_heart_answers jha
                        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                        WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS jack_heart_score,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    (
                        COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                            SELECT COALESCE(SUM(mr.round_score), 0)
                            FROM mindmaze_results mr
                            JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                            WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                            SELECT COALESCE(SUM(asr.round_score), 0)
                            FROM ace_spade_results asr
                            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                            WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, GREATEST(0.0,
                            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
                            - COALESCE((
                                SELECT SUM(kds.round_score)
                                FROM king_diamond_submissions kds
                                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                            ), 0.0)
                        )) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                            SELECT COALESCE(SUM(jha.round_score), 0)
                            FROM jack_heart_answers jha
                            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                        ), 0) ELSE 0 END, 0)
                    )::FLOAT
                ELSE NULL
            END AS total_score,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    RANK() OVER (
                        PARTITION BY r.room_id
                        ORDER BY (
                            COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                                SELECT COALESCE(SUM(mr.round_score), 0)
                                FROM mindmaze_results mr
                                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                                SELECT COALESCE(SUM(asr.round_score), 0)
                                FROM ace_spade_results asr
                                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, (
                                SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                                FROM king_diamond_submissions kds
                                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                            ), 0.0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                                SELECT COALESCE(SUM(jha.round_score), 0)
                                FROM jack_heart_answers jha
                                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                            ), 0) ELSE 0 END, 0)
                        ) DESC, t.team_code
                    )::INT
                ELSE NULL
            END AS live_rank,
            CASE
                WHEN (rd.results_published_at IS NOT NULL) THEN
                    CASE WHEN rr.tiebreak_pending IS TRUE THEN NULL ELSE COALESCE(rr.is_qualified, FALSE) END
                ELSE NULL
            END AS is_qualified,
            (rd.results_published_at IS NOT NULL) AS is_published,
            COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending,
            FLOOR(EXTRACT(EPOCH FROM rd.results_published_at) * 1000)::BIGINT AS results_broadcast_id
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
        ORDER BY live_rank NULLS LAST, t.team_code;
    """)
    rows = (await db.execute(query, {"room_id": str(room_id)})).mappings().all()
    return [RoomLeaderboardEntry(**row) for row in rows]


@router.get("/overall", response_model=list[OverallLeaderboardEntry])
async def get_overall_leaderboard(db: AsyncSession = Depends(get_db), _current_team=Depends(get_current_team)):
    query = text("""
        SELECT
            t.team_code,
            t.team_name,
            st.code AS team_suit_code,
            st.symbol AS team_suit_symbol,
            COALESCE(r.room_code, '—') AS room_code,
            CASE
                WHEN smm.is_published IS TRUE THEN
                    COALESCE(mm.score, (
                        SELECT COALESCE(SUM(mr.round_score), 0)
                        FROM mindmaze_results mr
                        JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                        WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS mindmaze_score,
            CASE
                WHEN sas.is_published IS TRUE THEN
                    COALESCE(as_.score, (
                        SELECT COALESCE(SUM(asr.round_score), 0)
                        FROM ace_spade_results asr
                        JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                        WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS ace_spade_score,
            CASE
                WHEN skd.is_published IS TRUE THEN
                    COALESCE(kd.score, (
                        SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                        FROM king_diamond_submissions kds
                        JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                        WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                    ), 0.0)::FLOAT
                ELSE NULL
            END AS king_diamond_score,
            CASE
                WHEN sjh.is_published IS TRUE THEN
                    COALESCE(jh.score, (
                        SELECT COALESCE(SUM(jha.round_score), 0)
                        FROM jack_heart_answers jha
                        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                        WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                    ), 0)::FLOAT
                ELSE NULL
            END AS jack_heart_score,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    (
                        COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                            SELECT COALESCE(SUM(mr.round_score), 0)
                            FROM mindmaze_results mr
                            JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                            WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                            SELECT COALESCE(SUM(asr.round_score), 0)
                            FROM ace_spade_results asr
                            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                            WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                        ), 0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, (
                            SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                            FROM king_diamond_submissions kds
                            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                        ), 0.0) ELSE 0 END, 0) +
                        COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                            SELECT COALESCE(SUM(jha.round_score), 0)
                            FROM jack_heart_answers jha
                            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                        ), 0) ELSE 0 END, 0)
                    )::FLOAT
                ELSE NULL
            END AS total_score,
            CASE
                WHEN (rd.results_published_at IS NOT NULL) THEN
                    CASE WHEN rr.tiebreak_pending IS TRUE THEN NULL ELSE COALESCE(rr.is_qualified, FALSE) END
                ELSE NULL
            END AS is_qualified,
            CASE
                WHEN (smm.is_published IS TRUE OR sas.is_published IS TRUE OR skd.is_published IS TRUE OR sjh.is_published IS TRUE) THEN
                    RANK() OVER (
                        ORDER BY (
                            COALESCE(CASE WHEN smm.is_published IS TRUE THEN COALESCE(mm.score, (
                                SELECT COALESCE(SUM(mr.round_score), 0)
                                FROM mindmaze_results mr
                                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sas.is_published IS TRUE THEN COALESCE(as_.score, (
                                SELECT COALESCE(SUM(asr.round_score), 0)
                                FROM ace_spade_results asr
                                JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
                                WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
                            ), 0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN skd.is_published IS TRUE THEN COALESCE(kd.score, (
                                SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                                FROM king_diamond_submissions kds
                                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                            ), 0.0) ELSE 0 END, 0) +
                            COALESCE(CASE WHEN sjh.is_published IS TRUE THEN COALESCE(jh.score, (
                                SELECT COALESCE(SUM(jha.round_score), 0)
                                FROM jack_heart_answers jha
                                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
                            ), 0) ELSE 0 END, 0)
                        ) DESC, t.team_code
                    )::INT
                ELSE NULL
            END AS overall_rank,
            (rd.results_published_at IS NOT NULL) AS is_published,
            COALESCE(rr.tiebreak_pending, FALSE) AS tiebreak_pending,
            FLOOR(EXTRACT(EPOCH FROM rd.results_published_at) * 1000)::BIGINT AS results_broadcast_id
        FROM teams t
        LEFT JOIN round1_selections rs ON rs.team_id = t.team_id
        LEFT JOIN suits st ON st.suit_id = rs.suit_id
        LEFT JOIN rooms r ON r.room_id = rs.room_id
        LEFT JOIN rounds rd ON rd.round_id = r.round_id
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
        ORDER BY overall_rank NULLS LAST, t.team_code;
    """)
    rows = (await db.execute(query)).mappings().all()
    return [OverallLeaderboardEntry(**row) for row in rows]


@router.get("/games/{game_code}", response_model=list[GameLeaderboardEntry])
async def get_game_leaderboard(
    game_code: str, db: AsyncSession = Depends(get_db), _current_team=Depends(get_current_team)
):
    query = text("""
        SELECT 
            g.code AS game_code,
            g.name AS game_name,
            r.room_code,
            t.team_code,
            t.team_name,
            st.code AS team_suit_code,
            st.symbol AS team_suit_symbol,
            gs_score.score,
            RANK() OVER (PARTITION BY g.game_id ORDER BY gs_score.score DESC) AS game_rank
        FROM game_scores gs_score
        JOIN game_sessions se ON se.session_id = gs_score.session_id AND se.is_published IS TRUE
        JOIN games g ON g.game_id = se.game_id
        JOIN rooms r ON r.room_id = se.room_id
        JOIN teams t ON t.team_id = gs_score.team_id
        LEFT JOIN round1_selections rs ON rs.team_id = t.team_id AND rs.room_id = r.room_id
        LEFT JOIN suits st ON st.suit_id = rs.suit_id
        WHERE g.code = :code
        ORDER BY game_rank;
    """)
    rows = (
        await db.execute(
            query,
            {"code": game_code.upper()},
        )
    ).mappings().all()
    return [GameLeaderboardEntry(**row) for row in rows]

