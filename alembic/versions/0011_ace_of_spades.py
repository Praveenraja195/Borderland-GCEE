"""ace of spades game — tables, scoring trigger, room_results column, views

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-08

Adds the fourth game (Ace of Spades — 8-card order recall with 2 decoys,
+2.0 per correctly-placed card / -0.5 per wrong pick, floored at 0) as a
sibling of MindMaze: its own games row, ace_spade_rounds/ace_spade_results
tables with the same scoring-trigger shape as fn_score_mindmaze_result, a
new ace_spade_score column on room_results folded into the generated
total_score, and fn_compute_room_results/v_room_leaderboard/
v_overall_leaderboard updated to include it. See sql/round1_schema.sql for
the equivalent full-schema statement of the same end state.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO games (code, name, description) VALUES
            ('ACE_SPADE', 'Ace of Spades', 'Card order + decoy memory recall game, 5 rounds')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO round_games (round_id, game_id, game_order)
        SELECT r.round_id, g.game_id, COALESCE((SELECT MAX(rg.game_order) FROM round_games rg WHERE rg.round_id = r.round_id), 0) + 1
        FROM rounds r, games g
        WHERE g.code = 'ACE_SPADE'
        AND NOT EXISTS (
            SELECT 1 FROM round_games rg WHERE rg.round_id = r.round_id AND rg.game_id = g.game_id
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ace_spade_rounds (
            round_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id      UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
            round_number    SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
            start_time      TIMESTAMPTZ,
            deadline        TIMESTAMPTZ,
            UNIQUE (session_id, round_number)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ace_spade_results (
            result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            round_id            UUID NOT NULL REFERENCES ace_spade_rounds(round_id) ON DELETE CASCADE,
            team_id             UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
            moves               INT NOT NULL CHECK (moves >= 0),
            wrong_picks         INT NOT NULL CHECK (wrong_picks >= 0),
            correct_picks       INT NOT NULL CHECK (correct_picks >= 0),
            completion_time     INTERVAL,
            round_score         NUMERIC(8,2) NOT NULL DEFAULT 0,
            submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (round_id, team_id)
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_as_results_team ON ace_spade_results(team_id)")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_score_ace_spade_result()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.round_score := GREATEST(
                0,
                (NEW.correct_picks * 2.0) - (NEW.wrong_picks * 0.5)
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_as_score ON ace_spade_results")
    op.execute(
        """
        CREATE TRIGGER trg_as_score
        BEFORE INSERT ON ace_spade_results
        FOR EACH ROW EXECUTE FUNCTION fn_score_ace_spade_result()
        """
    )

    # room_results.total_score is a GENERATED ALWAYS column — its expression
    # can't be altered in place, so drop and re-add it alongside the new
    # ace_spade_score column.
    op.execute("ALTER TABLE room_results DROP COLUMN IF EXISTS total_score")
    op.execute("ALTER TABLE room_results ADD COLUMN IF NOT EXISTS ace_spade_score NUMERIC(8,2) NOT NULL DEFAULT 0")
    op.execute(
        """
        ALTER TABLE room_results ADD COLUMN total_score NUMERIC(9,2) GENERATED ALWAYS AS
            (mindmaze_score + ace_spade_score + king_diamond_score + jack_heart_score) STORED
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_compute_room_results(p_room_id UUID)
        RETURNS VOID AS $$
        BEGIN
            INSERT INTO room_results (room_id, team_id, mindmaze_score, ace_spade_score, king_diamond_score, jack_heart_score)
            SELECT p_room_id, t.team_id,
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
                       SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0))
                       FROM king_diamond_submissions kds
                       JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                       WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
                   ), 30.0),
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
        END;
        $$ LANGUAGE plpgsql;
        """
    )

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


def downgrade() -> None:
    # Restore the pre-0011 views/function (3-game shape) before dropping
    # the column they'd otherwise still reference.
    op.execute("DROP VIEW IF EXISTS v_room_leaderboard CASCADE")
    op.execute(
        """
        CREATE OR REPLACE VIEW v_room_leaderboard AS
        SELECT
            r.room_id, r.room_code, t.team_code, t.team_name,
            COALESCE(mm.score, (
                SELECT COALESCE(SUM(mr.round_score), 0) FROM mindmaze_results mr
                JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id
                WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id
            ), 0)::FLOAT AS mindmaze_score,
            COALESCE(kd.score, (
                SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0)) FROM king_diamond_submissions kds
                JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id
                WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE
            ), 30.0)::FLOAT AS king_diamond_score,
            COALESCE(jh.score, (
                SELECT COALESCE(SUM(jha.round_score), 0) FROM jack_heart_answers jha
                JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id
                WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id
            ), 0)::FLOAT AS jack_heart_score,
            (COALESCE(mm.score, 0) + COALESCE(kd.score, 30.0) + COALESCE(jh.score, 0))::FLOAT AS total_score,
            RANK() OVER (PARTITION BY r.room_id ORDER BY (COALESCE(mm.score, 0) + COALESCE(kd.score, 30.0) + COALESCE(jh.score, 0)) DESC, t.team_code)::INT AS live_rank,
            COALESCE(rr.is_qualified, FALSE) AS is_qualified
        FROM teams t
        JOIN round1_selections rs ON rs.team_id = t.team_id
        JOIN rooms r ON r.room_id = rs.room_id
        LEFT JOIN game_sessions smm ON smm.room_id = r.room_id AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
        LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
        LEFT JOIN game_sessions skd ON skd.room_id = r.room_id AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
        LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
        LEFT JOIN game_sessions sjh ON sjh.room_id = r.room_id AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
        LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
        LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id;
        """
    )

    op.execute("DROP VIEW IF EXISTS v_overall_leaderboard CASCADE")
    op.execute(
        """
        CREATE OR REPLACE VIEW v_overall_leaderboard AS
        SELECT
            t.team_code, t.team_name, r.room_code,
            COALESCE(mm.score, 0)::FLOAT AS mindmaze_score,
            COALESCE(kd.score, 30.0)::FLOAT AS king_diamond_score,
            COALESCE(jh.score, 0)::FLOAT AS jack_heart_score,
            (COALESCE(mm.score, 0) + COALESCE(kd.score, 30.0) + COALESCE(jh.score, 0))::FLOAT AS total_score,
            COALESCE(rr.is_qualified, FALSE) AS is_qualified,
            RANK() OVER (ORDER BY (COALESCE(mm.score, 0) + COALESCE(kd.score, 30.0) + COALESCE(jh.score, 0)) DESC, t.team_code)::INT AS overall_rank
        FROM teams t
        JOIN round1_selections rs ON rs.team_id = t.team_id
        JOIN rooms r ON r.room_id = rs.room_id
        LEFT JOIN game_sessions smm ON smm.room_id = r.room_id AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
        LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
        LEFT JOIN game_sessions skd ON skd.room_id = r.room_id AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
        LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
        LEFT JOIN game_sessions sjh ON sjh.room_id = r.room_id AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
        LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
        LEFT JOIN room_results rr ON rr.room_id = r.room_id AND rr.team_id = t.team_id;

        CREATE OR REPLACE FUNCTION fn_compute_room_results(p_room_id UUID)
        RETURNS VOID AS $$
        BEGIN
            INSERT INTO room_results (room_id, team_id, mindmaze_score, king_diamond_score, jack_heart_score)
            SELECT p_room_id, t.team_id,
                   COALESCE(mm.score, (SELECT COALESCE(SUM(mr.round_score), 0) FROM mindmaze_results mr JOIN mindmaze_rounds mrd ON mrd.round_id = mr.round_id WHERE mrd.session_id = smm.session_id AND mr.team_id = t.team_id), 0),
                   COALESCE(kd.score, (SELECT GREATEST(0.0, 30.0 - COALESCE(SUM(kds.round_score), 0)) FROM king_diamond_submissions kds JOIN king_diamond_rounds kdr ON kdr.round_id = kds.round_id WHERE kdr.session_id = skd.session_id AND kds.team_id = t.team_id AND kdr.is_closed IS TRUE), 30.0),
                   COALESCE(jh.score, (SELECT COALESCE(SUM(jha.round_score), 0) FROM jack_heart_answers jha JOIN jack_heart_rounds jhr ON jhr.round_id = jha.round_id WHERE jhr.session_id = sjh.session_id AND jha.team_id = t.team_id), 0)
              FROM teams t
              JOIN round1_selections rs ON rs.team_id = t.team_id AND rs.room_id = p_room_id
              LEFT JOIN game_sessions smm ON smm.room_id = p_room_id AND smm.game_id = (SELECT game_id FROM games WHERE code = 'MINDMAZE')
              LEFT JOIN game_scores mm ON mm.session_id = smm.session_id AND mm.team_id = t.team_id
              LEFT JOIN game_sessions skd ON skd.room_id = p_room_id AND skd.game_id = (SELECT game_id FROM games WHERE code = 'KING_DIAMOND')
              LEFT JOIN game_scores kd ON kd.session_id = skd.session_id AND kd.team_id = t.team_id
              LEFT JOIN game_sessions sjh ON sjh.room_id = p_room_id AND sjh.game_id = (SELECT game_id FROM games WHERE code = 'JACK_HEART')
              LEFT JOIN game_scores jh ON jh.session_id = sjh.session_id AND jh.team_id = t.team_id
            ON CONFLICT (room_id, team_id) DO UPDATE
                SET mindmaze_score = EXCLUDED.mindmaze_score,
                    king_diamond_score = EXCLUDED.king_diamond_score,
                    jack_heart_score = EXCLUDED.jack_heart_score,
                    computed_at = now();

            WITH ranked AS (
                SELECT result_id, RANK() OVER (ORDER BY total_score DESC) AS rnk FROM room_results WHERE room_id = p_room_id
            )
            UPDATE room_results rr SET rank = ranked.rnk FROM ranked WHERE rr.result_id = ranked.result_id;

            UPDATE room_results rr
               SET is_qualified = (rr.rank <= COALESCE(
                     (SELECT qr.top_n FROM qualification_rules qr JOIN rooms rm ON rm.round_id = qr.round_id
                       WHERE rm.room_id = rr.room_id AND (qr.room_id = rr.room_id OR qr.room_id IS NULL)
                       ORDER BY qr.room_id NULLS LAST LIMIT 1), 1))
             WHERE rr.room_id = p_room_id;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute("ALTER TABLE room_results DROP COLUMN IF EXISTS total_score")
    op.execute("ALTER TABLE room_results DROP COLUMN IF EXISTS ace_spade_score")
    op.execute(
        """
        ALTER TABLE room_results ADD COLUMN total_score NUMERIC(9,2) GENERATED ALWAYS AS
            (mindmaze_score + king_diamond_score + jack_heart_score) STORED
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_as_score ON ace_spade_results")
    op.execute("DROP FUNCTION IF EXISTS fn_score_ace_spade_result CASCADE")
    op.execute("DROP TABLE IF EXISTS ace_spade_results CASCADE")
    op.execute("DROP TABLE IF EXISTS ace_spade_rounds CASCADE")
    op.execute("DELETE FROM round_games WHERE game_id IN (SELECT game_id FROM games WHERE code = 'ACE_SPADE')")
    op.execute("DELETE FROM games WHERE code = 'ACE_SPADE'")
