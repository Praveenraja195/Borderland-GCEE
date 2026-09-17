"""publish_final_results_gate

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-09

Strictly gate is_published and is_qualified behind rd.status = 'COMPLETED'
in v_room_leaderboard and v_overall_leaderboard so that publishing individual
games (such as Jack of Hearts) does not prematurely trigger overall qualification
outcomes (Sky Laser strike / VISA Extended).
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

VIEW_ROOM_LEADERBOARD_SQL = """
CREATE OR REPLACE VIEW v_room_leaderboard AS
SELECT
    r.room_id,
    r.room_code,
    t.team_code,
    t.team_name,
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
    COALESCE(kd.score, GREATEST(0.0,
        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
        - COALESCE((
            SELECT SUM(kds.round_score)
            FROM king_diamond_submissions kds
            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
        ), 0.0)
    ))::FLOAT AS king_diamond_score,
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
    ) + COALESCE(kd.score, GREATEST(0.0,
        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
        - COALESCE((
            SELECT SUM(kds.round_score)
            FROM king_diamond_submissions kds
            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
        ), 0.0)
    )) + COALESCE(jh.score, (
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
        ) + COALESCE(kd.score, GREATEST(0.0,
            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
            - COALESCE((
                SELECT SUM(kds.round_score)
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 0.0)
        )) + COALESCE(jh.score, (
            SELECT COALESCE(SUM(jha.round_score), 0)
            FROM jack_heart_answers jha
            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
        ), 0)) DESC, t.team_code
    )::INT AS live_rank,
    CASE
        WHEN rd.status = 'COMPLETED' THEN COALESCE(rr.is_qualified, FALSE)
        ELSE NULL
    END AS is_qualified,
    (rd.status = 'COMPLETED') AS is_published
FROM teams t
JOIN round1_selections rs ON rs.team_id = t.team_id
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
LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id;
"""

VIEW_OVERALL_LEADERBOARD_SQL = """
CREATE OR REPLACE VIEW v_overall_leaderboard AS
SELECT
    t.team_code,
    t.team_name,
    r.room_code,
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
    COALESCE(kd.score, GREATEST(0.0,
        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
        - COALESCE((
            SELECT SUM(kds.round_score)
            FROM king_diamond_submissions kds
            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
        ), 0.0)
    ))::FLOAT AS king_diamond_score,
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
    ), 0) + COALESCE(kd.score, GREATEST(0.0,
        COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
        - COALESCE((
            SELECT SUM(kds.round_score)
            FROM king_diamond_submissions kds
            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
            WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
        ), 0.0)
    )) + COALESCE(jh.score, (
        SELECT COALESCE(SUM(jha.round_score), 0)
        FROM jack_heart_answers jha
        JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
        WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
    ), 0))::FLOAT AS total_score,
    CASE
        WHEN rd.status = 'COMPLETED' THEN COALESCE(rr.is_qualified, FALSE)
        ELSE NULL
    END AS is_qualified,
    RANK() OVER (
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
        ), 0) + COALESCE(kd.score, GREATEST(0.0,
            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
            - COALESCE((
                SELECT SUM(kds.round_score)
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 0.0)
        )) + COALESCE(jh.score, (
            SELECT COALESCE(SUM(jha.round_score), 0)
            FROM jack_heart_answers jha
            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
        ), 0)) DESC, t.team_code
    )::INT AS overall_rank,
    (rd.status = 'COMPLETED') AS is_published
FROM teams t
JOIN round1_selections rs ON rs.team_id = t.team_id
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
LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id;
"""


def upgrade() -> None:
    op.execute(VIEW_ROOM_LEADERBOARD_SQL)
    op.execute(VIEW_OVERALL_LEADERBOARD_SQL)


def downgrade() -> None:
    pass
