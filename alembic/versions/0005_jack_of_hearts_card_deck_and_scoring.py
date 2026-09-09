"""jack of hearts card deck and scoring (+5.0 / -2.5)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-15

Updates jh_symbols to 40 playing cards across 4 suits (Spades, Hearts,
Diamonds, Clubs) with ranks A through 10, and updates the scoring trigger
fn_validate_jh_answer to award +5.0 points on correct guess and -2.5 points
on incorrect guess.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add suit and rank columns to jh_symbols
    op.execute("ALTER TABLE jh_symbols ADD COLUMN IF NOT EXISTS suit TEXT")
    op.execute("ALTER TABLE jh_symbols ADD COLUMN IF NOT EXISTS rank TEXT")

    # 2. Populate 40 cards
    cards = [
        # Spades ♠
        (1, "SPADE_A", "♠ A", "SPADE", "A"),
        (2, "SPADE_2", "♠ 2", "SPADE", "2"),
        (3, "SPADE_3", "♠ 3", "SPADE", "3"),
        (4, "SPADE_4", "♠ 4", "SPADE", "4"),
        (5, "SPADE_5", "♠ 5", "SPADE", "5"),
        (6, "SPADE_6", "♠ 6", "SPADE", "6"),
        (7, "SPADE_7", "♠ 7", "SPADE", "7"),
        (8, "SPADE_8", "♠ 8", "SPADE", "8"),
        (9, "SPADE_9", "♠ 9", "SPADE", "9"),
        (10, "SPADE_10", "♠ 10", "SPADE", "10"),
        # Hearts ♥
        (11, "HEART_A", "♥ A", "HEART", "A"),
        (12, "HEART_2", "♥ 2", "HEART", "2"),
        (13, "HEART_3", "♥ 3", "HEART", "3"),
        (14, "HEART_4", "♥ 4", "HEART", "4"),
        (15, "HEART_5", "♥ 5", "HEART", "5"),
        (16, "HEART_6", "♥ 6", "HEART", "6"),
        (17, "HEART_7", "♥ 7", "HEART", "7"),
        (18, "HEART_8", "♥ 8", "HEART", "8"),
        (19, "HEART_9", "♥ 9", "HEART", "9"),
        (20, "HEART_10", "♥ 10", "HEART", "10"),
        # Diamonds ♦
        (21, "DIAMOND_A", "♦ A", "DIAMOND", "A"),
        (22, "DIAMOND_2", "♦ 2", "DIAMOND", "2"),
        (23, "DIAMOND_3", "♦ 3", "DIAMOND", "3"),
        (24, "DIAMOND_4", "♦ 4", "DIAMOND", "4"),
        (25, "DIAMOND_5", "♦ 5", "DIAMOND", "5"),
        (26, "DIAMOND_6", "♦ 6", "DIAMOND", "6"),
        (27, "DIAMOND_7", "♦ 7", "DIAMOND", "7"),
        (28, "DIAMOND_8", "♦ 8", "DIAMOND", "8"),
        (29, "DIAMOND_9", "♦ 9", "DIAMOND", "9"),
        (30, "DIAMOND_10", "♦ 10", "DIAMOND", "10"),
        # Clubs ♣
        (31, "CLUB_A", "♣ A", "CLUB", "A"),
        (32, "CLUB_2", "♣ 2", "CLUB", "2"),
        (33, "CLUB_3", "♣ 3", "CLUB", "3"),
        (34, "CLUB_4", "♣ 4", "CLUB", "4"),
        (35, "CLUB_5", "♣ 5", "CLUB", "5"),
        (36, "CLUB_6", "♣ 6", "CLUB", "6"),
        (37, "CLUB_7", "♣ 7", "CLUB", "7"),
        (38, "CLUB_8", "♣ 8", "CLUB", "8"),
        (39, "CLUB_9", "♣ 9", "CLUB", "9"),
        (40, "CLUB_10", "♣ 10", "CLUB", "10"),
    ]

    for sid, code, label, suit, rank in cards:
        op.execute(
            f"""
            INSERT INTO jh_symbols (symbol_id, code, label, suit, rank)
            VALUES ({sid}, '{code}', '{label}', '{suit}', '{rank}')
            ON CONFLICT (symbol_id) DO UPDATE
            SET code = EXCLUDED.code,
                label = EXCLUDED.label,
                suit = EXCLUDED.suit,
                rank = EXCLUDED.rank;
            """
        )

    # 3. Update fn_validate_jh_answer trigger function
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
                NEW.round_score := 100;
            ELSE
                NEW.round_score := 0;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("ALTER TABLE jh_symbols DROP COLUMN IF EXISTS rank")
    op.execute("ALTER TABLE jh_symbols DROP COLUMN IF EXISTS suit")
