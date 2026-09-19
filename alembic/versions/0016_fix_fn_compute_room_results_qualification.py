"""fix_fn_compute_room_results_qualification

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-19

Ensure fn_compute_room_results computes is_qualified whenever the round or room
is marked COMPLETED, or all configured game sessions in the room are published,
rather than strictly requiring published_games_count = 4.
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

NEW_FN_COMPUTE_ROOM_RESULTS_SQL = """
CREATE OR REPLACE FUNCTION fn_compute_room_results(p_room_id UUID)
RETURNS VOID AS $$
DECLARE
    published_games_count INT;
    configured_games_count INT;
    is_round_or_room_completed BOOLEAN;
BEGIN
    INSERT INTO room_results (room_id, team_id, mindmaze_score, ace_spade_score, king_diamond_score, jack_heart_score)
    SELECT
        p_room_id,
        t.team_id,
        COALESCE(mm.score, (
            SELECT COALESCE(SUM(mr.round_score), 0)
            FROM mindmaze_results mr
            JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
            WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
        ), 0),
        COALESCE(as_.score, (
            SELECT COALESCE(SUM(asr.round_score), 0)
            FROM ace_spade_results asr
            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
            WHERE asrd.session_id = sas.session_id AND asr.team_id = t.team_id
        ), 0),
        COALESCE(kd.score, GREATEST(0.0,
            COALESCE(NULLIF((SELECT COUNT(*) FROM king_diamond_rounds WHERE session_id = skd.session_id), 0), 5) * 20.0
            - COALESCE((
                SELECT SUM(kds.round_score)
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 0.0)
        )),
        COALESCE(jh.score, (
            SELECT COALESCE(SUM(jha.round_score), 0)
            FROM jack_heart_answers jha
            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
            WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
        ), 0)
    FROM teams t
    JOIN round1_selections rs ON rs.team_id = t.team_id AND rs.room_id = p_room_id
    LEFT JOIN game_sessions smm ON smm.room_id = p_room_id
           AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
    LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
    LEFT JOIN game_sessions sas ON sas.room_id = p_room_id
           AND sas.game_id = (SELECT game_id FROM games WHERE code = 'ACE_SPADE')
    LEFT JOIN game_scores as_ ON as_.session_id = sas.session_id AND as_.team_id = t.team_id
    LEFT JOIN game_sessions skd ON skd.room_id = p_room_id
           AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
    LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
    LEFT JOIN game_sessions sjh ON sjh.room_id = p_room_id
           AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
    LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
    ON CONFLICT (room_id, team_id) DO UPDATE
        SET mindmaze_score     = EXCLUDED.mindmaze_score,
            ace_spade_score    = EXCLUDED.ace_spade_score,
            king_diamond_score = EXCLUDED.king_diamond_score,
            jack_heart_score   = EXCLUDED.jack_heart_score,
            computed_at        = now();

    WITH ranked AS (
        SELECT result_id, RANK() OVER (ORDER BY total_score DESC) AS rnk
          FROM room_results
         WHERE room_id = p_room_id
    )
    UPDATE room_results rr
       SET rank = ranked.rnk
      FROM ranked
     WHERE rr.result_id = ranked.result_id;

    SELECT COUNT(DISTINCT g.code) INTO published_games_count
    FROM game_sessions gs
    JOIN games g ON g.game_id = gs.game_id
    WHERE gs.room_id = p_room_id AND gs.is_published IS TRUE;

    SELECT COUNT(*) INTO configured_games_count
    FROM round_games rg
    JOIN rooms rm ON rm.round_id = rg.round_id
    WHERE rm.room_id = p_room_id;

    SELECT (rd.status = 'COMPLETED' OR rm.status = 'COMPLETED') INTO is_round_or_room_completed
    FROM rooms rm
    JOIN rounds rd ON rd.round_id = rm.round_id
    WHERE rm.room_id = p_room_id;

    IF (is_round_or_room_completed IS TRUE) OR 
       (configured_games_count > 0 AND published_games_count >= configured_games_count) OR 
       (published_games_count >= 4) THEN
        UPDATE room_results rr
           SET is_qualified = (rr.rank <= COALESCE(
                 (SELECT qr.top_n
                    FROM qualification_rules qr
                    JOIN rooms rm ON rm.round_id = qr.round_id
                   WHERE rm.room_id = rr.room_id
                     AND (qr.room_id = rr.room_id OR qr.room_id IS NULL)
                   ORDER BY qr.room_id NULLS LAST
                   LIMIT 1), 1))
         WHERE rr.room_id = p_room_id;
    ELSE
        UPDATE room_results rr
           SET is_qualified = FALSE
         WHERE rr.room_id = p_room_id;
    END IF;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute(NEW_FN_COMPUTE_ROOM_RESULTS_SQL)


def downgrade() -> None:
    pass
