"""jack of hearts scoring update: 0 penalty on incorrect answer

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-15

Updates fn_validate_jh_answer to give 5.0 points on correct guess and 0 points
on incorrect guess (no negative point reduction).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
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
                NEW.round_score := -2.5;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
