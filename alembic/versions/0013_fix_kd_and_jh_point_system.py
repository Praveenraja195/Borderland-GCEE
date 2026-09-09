"""fix king of diamonds and jack of hearts point systems

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-09

Updates fn_validate_jh_answer to award 10.0 points (instead of 5.0) on correct guess,
recreates v_room_leaderboard and v_overall_leaderboard to use 100.0 base for King of Diamonds
(instead of 30.0), updates king_diamond_submissions invalid forfeit penalties to 20.0,
recalculates game_scores for KD and JH, and recomputes room_results.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update fn_validate_jh_answer to give 10.0 points for correct guesses
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_validate_jh_answer()
        RETURNS TRIGGER AS $$
        DECLARE
            v_actual SMALLINT;
        BEGIN
            SELECT symbol_id INTO v_actual
              FROM jack_heart_assignments
             WHERE round_id = NEW.round_id AND team_id = NEW.team_id;

            IF v_actual IS NULL THEN
                RAISE EXCEPTION 'No symbol assignment found for team % in round %', NEW.team_id, NEW.round_id;
            END IF;

            NEW.actual_symbol_id := v_actual;
            IF NEW.submitted_symbol_id = v_actual THEN
                NEW.round_score := 10.0;
            ELSE
                NEW.round_score := 0.0;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 2. Recalculate existing jack_heart_answers if any exist
    op.execute(
        """
        UPDATE jack_heart_answers
        SET round_score = CASE WHEN is_correct THEN 10.0 ELSE 0.0 END;
        """
    )

    # 3. Update king_diamond_submissions invalid forfeit penalties from 30.0 to 20.0 (one round base)
    op.execute(
        """
        UPDATE king_diamond_submissions
        SET round_score = 20.0
        WHERE is_valid IS FALSE AND round_score = 30.0;
        """
    )

    # 4. Recreate v_room_leaderboard with 100.0 base for King of Diamonds
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
                SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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
                SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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
                    SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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

    # 5. Recreate v_overall_leaderboard with 100.0 base for King of Diamonds
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
                SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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
                SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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
                    SELECT GREATEST(0.0, 100.0 - COALESCE(SUM(kds.round_score), 0))
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

    # 6. Recalculate game_scores for KD sessions (100.0 - total_penalty)
    op.execute(
        """
        UPDATE game_scores gs
        SET score = GREATEST(0.0, 100.0 - sub.total_penalty)
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

    # 7. Recalculate game_scores for JH sessions
    op.execute(
        """
        UPDATE game_scores gs
        SET score = sub.total_score
        FROM (
            SELECT jhr.session_id, jha.team_id, COALESCE(SUM(jha.round_score), 0.0) AS total_score
            FROM jack_heart_answers jha
            JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
            GROUP BY jhr.session_id, jha.team_id
        ) sub
        WHERE gs.session_id = sub.session_id AND gs.team_id = sub.team_id;
        """
    )

    # 8. Recompute room_results for affected rooms
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
                  AND g.code IN ('KING_DIAMOND', 'JACK_HEART')
            ) LOOP
                PERFORM fn_compute_room_results(r.room_id);
            END LOOP;
        END;
        $$;
        """
    )


def downgrade() -> None:
    # 1. Revert fn_validate_jh_answer to 5.0
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_validate_jh_answer()
        RETURNS TRIGGER AS $$
        DECLARE
            v_actual SMALLINT;
        BEGIN
            SELECT symbol_id INTO v_actual
              FROM jack_heart_assignments
             WHERE round_id = NEW.round_id AND team_id = NEW.team_id;

            IF v_actual IS NULL THEN
                RAISE EXCEPTION 'No symbol assignment found for team % in round %', NEW.team_id, NEW.round_id;
            END IF;

            NEW.actual_symbol_id := v_actual;
            IF NEW.submitted_symbol_id = v_actual THEN
                NEW.round_score := 5.0;
            ELSE
                NEW.round_score := 0.0;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 2. Revert v_room_leaderboard
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
                SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 30.0)::FLOAT AS king_diamond_score,
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
                SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 30.0) + COALESCE(jh.score, (
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
                    SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                    FROM king_diamond_submissions kds
                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                ), 30.0) + COALESCE(jh.score, (
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

    # 3. Revert v_overall_leaderboard
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
                SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 30.0)::FLOAT AS king_diamond_score,
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
                SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 30.0) + COALESCE(jh.score, (
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
                    SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                    FROM king_diamond_submissions kds
                    JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                    WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                ), 30.0) + COALESCE(jh.score, (
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
