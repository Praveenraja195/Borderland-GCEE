"""dynamic king of diamonds rounds scoring

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09

Updates fn_compute_room_results, v_room_leaderboard, and v_overall_leaderboard
to dynamically calculate King of Diamonds base points as (number of rounds * 20.0)
for each session rather than hardcoding 5 rounds (100.0 pts).
Also recalculates game_scores and room_results.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Recreate fn_compute_room_results with dynamic KD round count
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_compute_room_results(p_room_id UUID)
        RETURNS VOID AS $$
        DECLARE
            published_games_count INT;
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
                COALESCE(kd.score, (
                    SELECT GREATEST(0.0, (SELECT COALESCE(COUNT(*), 5) * 20.0 FROM king_diamond_rounds WHERE session_id = skd.session_id) - COALESCE(SUM(kds.round_score), 0))
                    FROM king_diamond_submissions kds
                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                ), 0.0),
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

            IF published_games_count = 4 THEN
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
    )

    # 2. Recreate v_room_leaderboard with dynamic KD round count
    op.execute("DROP VIEW IF EXISTS v_room_leaderboard CASCADE")
    op.execute(
        """
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
            COALESCE(rr.is_qualified, FALSE) AS is_qualified
        FROM teams t
        JOIN round1_selections rs ON rs.team_id = t.team_id
        JOIN rooms r ON r.room_id = rs.room_id
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
    )

    # 3. Recreate v_overall_leaderboard with dynamic KD round count
    op.execute("DROP VIEW IF EXISTS v_overall_leaderboard CASCADE")
    op.execute(
        """
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
            COALESCE(rr.is_qualified, FALSE) AS is_qualified,
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
            )::INT AS overall_rank
        FROM teams t
        JOIN round1_selections rs ON rs.team_id = t.team_id
        JOIN rooms r ON r.room_id = rs.room_id
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
    )

    # 4. Recalculate game_scores for KD sessions dynamically
    op.execute(
        """
        UPDATE game_scores gs
        SET score = GREATEST(0.0, (
            SELECT COALESCE(COUNT(*), 5) * 20.0
            FROM king_diamond_rounds kdr
            WHERE kdr.session_id = gs.session_id
        ) - sub.total_penalty)
        FROM (
            SELECT kdr.session_id, kds.team_id, COALESCE(SUM(kds.round_score), 0.0) AS total_penalty
            FROM king_diamond_submissions kds
            JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
            WHERE kdr.is_closed IS TRUE
            GROUP BY kdr.session_id, kds.team_id
        ) sub
        WHERE gs.session_id = sub.session_id AND gs.team_id = sub.team_id;
        """
    )

    # 5. Recompute room_results
    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT DISTINCT gs.room_id
                FROM game_sessions gs
                JOIN games g ON g.game_id = gs.game_id
                WHERE gs.room_id IS NOT NULL
                  AND g.code = 'KING_DIAMOND'
            ) LOOP
                PERFORM fn_compute_room_results(r.room_id);
            END LOOP;
        END;
        $$;
        """
    )


def downgrade() -> None:
    pass
