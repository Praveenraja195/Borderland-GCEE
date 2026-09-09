"""fix ace of spades scoring trigger: 2.0 points per correct pick

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-09

Updates fn_score_ace_spade_result to give 2.0 points per correctly placed card
(instead of 1.0) minus 0.5 per wrong pick floored at 0, matching the game
specifications and ace_spade_service.compute_round_score. Also recalculates
existing rows in ace_spade_results, game_scores, and room_results.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        $$ LANGUAGE plpgsql;
        """
    )

    # Recalculate any existing ace_spade_results with the corrected trigger formula
    op.execute(
        """
        UPDATE ace_spade_results
        SET round_score = GREATEST(0, (correct_picks * 2.0) - (wrong_picks * 0.5));
        """
    )

    # Update running game_scores for affected sessions
    op.execute(
        """
        UPDATE game_scores gs
        SET score = sub.total_score
        FROM (
            SELECT asrd.session_id, asr.team_id, COALESCE(SUM(asr.round_score), 0.0) AS total_score
            FROM ace_spade_results asr
            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
            GROUP BY asrd.session_id, asr.team_id
        ) sub
        WHERE gs.session_id = sub.session_id AND gs.team_id = sub.team_id;
        """
    )

    # Recompute room_results for affected rooms
    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT DISTINCT gs.room_id
                FROM game_sessions gs
                JOIN ace_spade_rounds asrd ON asrd.session_id = gs.session_id
                JOIN ace_spade_results asr ON asr.round_id = asrd.round_id
                WHERE gs.room_id IS NOT NULL
            ) LOOP
                PERFORM fn_compute_room_results(r.room_id);
            END LOOP;
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_score_ace_spade_result()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.round_score := GREATEST(
                0,
                (NEW.correct_picks * 1.0) - (NEW.wrong_picks * 0.5)
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        """
        UPDATE ace_spade_results
        SET round_score = GREATEST(0, (correct_picks * 1.0) - (wrong_picks * 0.5));
        """
    )

    op.execute(
        """
        UPDATE game_scores gs
        SET score = sub.total_score
        FROM (
            SELECT asrd.session_id, asr.team_id, COALESCE(SUM(asr.round_score), 0.0) AS total_score
            FROM ace_spade_results asr
            JOIN ace_spade_rounds asrd ON asrd.round_id = asr.round_id
            GROUP BY asrd.session_id, asr.team_id
        ) sub
        WHERE gs.session_id = sub.session_id AND gs.team_id = sub.team_id;
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN (
                SELECT DISTINCT gs.room_id
                FROM game_sessions gs
                JOIN ace_spade_rounds asrd ON asrd.session_id = gs.session_id
                JOIN ace_spade_results asr ON asr.round_id = asrd.round_id
                WHERE gs.room_id IS NOT NULL
            ) LOOP
                PERFORM fn_compute_room_results(r.room_id);
            END LOOP;
        END;
        $$;
        """
    )
