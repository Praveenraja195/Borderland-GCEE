-- =====================================================================
-- ROUND 1 — CARD GAME EVENT DATABASE
-- PostgreSQL schema
-- =====================================================================
-- Design notes (see chat message for full rationale):
--  * UUID surrogate PKs everywhere, with a short human-readable *_code
--    column for display (T001, R03, ...).
--  * rooms are scoped to a round (round_id) so numbers 1-10 can be
--    reused safely in a future Round 2.
--  * Every "once only" / "server must generate this" rule from the
--    spec is enforced with a constraint or trigger, not left to the
--    application layer alone.
--  * Common game data lives in game_scores / game_sessions; game-
--    specific data lives in its own round + result tables.
-- =====================================================================

-- BEGIN;

-- ---------------------------------------------------------------------
-- 0. EXTENSIONS
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------
-- 1. ENUM TYPES
-- ---------------------------------------------------------------------
DO $$ BEGIN CREATE TYPE round_status   AS ENUM ('NOT_STARTED', 'ACTIVE', 'COMPLETED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE room_status    AS ENUM ('NOT_STARTED', 'ACTIVE', 'COMPLETED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE session_status AS ENUM ('NOT_STARTED', 'IN_PROGRESS', 'PAUSED', 'COMPLETED'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE admin_role     AS ENUM ('SUPER_ADMIN', 'ROOM_ADMIN'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------------------------------------------------------------------
-- 2. ADMINS (optional dashboard auth)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS admins (
    admin_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            admin_role NOT NULL DEFAULT 'ROOM_ADMIN',
    room_id         UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- 3. ROUNDS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rounds (
    round_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_number    SMALLINT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    status          round_status NOT NULL DEFAULT 'NOT_STARTED',
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_time IS NULL OR start_time IS NULL OR end_time > start_time)
);

-- ---------------------------------------------------------------------
-- 4. SUITS (reference table — grouping only, never affects room)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS suits (
    suit_id     SMALLSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,      -- HEART, SPADE, CLUB, DIAMOND
    symbol      TEXT NOT NULL
);

INSERT INTO suits (code, symbol) VALUES
    ('HEART',   '♥'),
    ('SPADE',   '♠'),
    ('CLUB',    '♣'),
    ('DIAMOND', '♦')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------
-- 5. TEAMS
-- ---------------------------------------------------------------------
-- leader_* are filled by the bulk registration import
-- (app/services/team_import_service.py) and are what the Round 2 winners
-- export uses to actually reach a qualifying team. Nullable: a team created
-- through the single-team admin form has no leader attached.
CREATE TABLE IF NOT EXISTS teams (
    team_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_code       TEXT NOT NULL UNIQUE,      -- B@GCEE-1234# (display / login)
    team_name       TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    leader_name     TEXT,
    leader_phone    TEXT,
    leader_email    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing databases created before migration 0010.
ALTER TABLE teams ADD COLUMN IF NOT EXISTS leader_name  TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS leader_phone TEXT;
ALTER TABLE teams ADD COLUMN IF NOT EXISTS leader_email TEXT;

-- Enforce the 40-team cap at the database level, not just in the app.
CREATE OR REPLACE FUNCTION fn_enforce_team_cap()
RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM teams) >= 40 THEN
        RAISE EXCEPTION 'Maximum of 40 teams already registered';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_team_cap ON teams;
CREATE TRIGGER trg_team_cap
BEFORE INSERT ON teams
FOR EACH ROW EXECUTE FUNCTION fn_enforce_team_cap();

-- ---------------------------------------------------------------------
-- 6. ROOMS (scoped to a round so numbers can be reused in Round 2+)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rooms (
    room_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id        UUID NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    room_number     SMALLINT NOT NULL CHECK (room_number BETWEEN 1 AND 10),
    room_code       TEXT NOT NULL,             -- R01..R10 (display)
    status          room_status NOT NULL DEFAULT 'NOT_STARTED',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_id, room_number),
    UNIQUE (round_id, room_code),
    UNIQUE (room_id, round_id)      -- lets game_sessions FK-check the (room, round) pair together
);

DO $$ BEGIN
    ALTER TABLE admins ADD CONSTRAINT fk_admins_room FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_admins_room ON admins(room_id);

-- ---------------------------------------------------------------------
-- 7. GAMES (global catalog: MindMaze / King of Diamonds / Jack of Hearts)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS games (
    game_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            TEXT NOT NULL UNIQUE,      -- MINDMAZE, KING_DIAMOND, JACK_HEART
    name            TEXT NOT NULL,
    description     TEXT,
    total_rounds    SMALLINT NOT NULL DEFAULT 5 CHECK (total_rounds > 0)
);

INSERT INTO games (code, name, description) VALUES
    ('MINDMAZE',     'MindMaze',            '16x16 memory tile game, 5 rounds'),
    ('ACE_SPADE',     'Ace of Spades',       'Card order + decoy memory recall game, 5 rounds'),
    ('KING_DIAMOND',  'King of Diamonds',    'Closest-to-target number game, 5 rounds'),
    ('JACK_HEART',    'Jack of Hearts',      'Hidden symbol deduction game, 5 rounds')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------
-- 7b. ROUND_GAMES — which games run in which round, and in what order.
-- Without this, game_sessions has no way to know "these 3 games belong
-- to Round 1" once a Round 2 with a different game lineup exists.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS round_games (
    round_id    UUID NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    game_id     UUID NOT NULL REFERENCES games(game_id),
    game_order  SMALLINT NOT NULL,
    PRIMARY KEY (round_id, game_id),
    UNIQUE (round_id, game_order)
);

-- ---------------------------------------------------------------------
-- 8. ROUND1_SELECTIONS  (suit + number, one-time, auto room assignment)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS round1_selections (
    selection_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id        UUID NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    team_id         UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    suit_id         SMALLINT NOT NULL REFERENCES suits(suit_id),
    selected_number SMALLINT NOT NULL CHECK (selected_number BETWEEN 1 AND 10),
    room_id         UUID REFERENCES rooms(room_id),      -- filled by trigger
    is_locked       BOOLEAN NOT NULL DEFAULT FALSE,
    selected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_id, team_id),                           -- Rule 3: once only
    CONSTRAINT uq_suit_number_per_round UNIQUE (round_id, suit_id, selected_number)
);

-- Auto-assign room from selected_number, and lock the row on insert
-- (selection is one-time by definition, so it is locked the moment it exists).
CREATE OR REPLACE FUNCTION fn_assign_room()
RETURNS TRIGGER AS $$
DECLARE
    v_room_id UUID;
BEGIN
    SELECT room_id INTO v_room_id
      FROM rooms
     WHERE round_id = NEW.round_id
       AND room_number = NEW.selected_number;

    IF v_room_id IS NULL THEN
        RAISE EXCEPTION 'No room configured for number % in round %',
            NEW.selected_number, NEW.round_id;
    END IF;

    NEW.room_id   := v_room_id;
    NEW.is_locked := TRUE;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_assign_room ON round1_selections;
CREATE TRIGGER trg_assign_room
BEFORE INSERT ON round1_selections
FOR EACH ROW EXECUTE FUNCTION fn_assign_room();

-- Block any modification once a selection exists (defence in depth,
-- in case someone tries an UPDATE instead of relying on app logic).
CREATE OR REPLACE FUNCTION fn_prevent_selection_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.is_locked THEN
        RAISE EXCEPTION 'Selection % is locked and cannot be modified', OLD.selection_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_lock_selection ON round1_selections;
CREATE TRIGGER trg_lock_selection
BEFORE UPDATE ON round1_selections
FOR EACH ROW EXECUTE FUNCTION fn_prevent_selection_update();

-- ---------------------------------------------------------------------
-- 9. GAME_SESSIONS (a game actually being run in a specific room)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_sessions (
    session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id    UUID NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    room_id     UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    game_id     UUID NOT NULL REFERENCES games(game_id),
    status      session_status NOT NULL DEFAULT 'NOT_STARTED',
    start_time  TIMESTAMPTZ,
    end_time    TIMESTAMPTZ,
    paused_at   TIMESTAMPTZ,
    instruction_until TIMESTAMPTZ,
    roster_team_ids JSONB,
    is_published BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (room_id, game_id),
    FOREIGN KEY (room_id, round_id) REFERENCES rooms(room_id, round_id),
    FOREIGN KEY (round_id, game_id) REFERENCES round_games(round_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_room ON game_sessions(room_id);
CREATE INDEX IF NOT EXISTS idx_sessions_round ON game_sessions(round_id);

-- ---------------------------------------------------------------------
-- 10. GAME_SCORES (common aggregate score per team per session)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS game_scores (
    score_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    team_id     UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    score       NUMERIC(8,2) NOT NULL DEFAULT 0,
    rank        SMALLINT,
    time_taken  INTERVAL,
    completed   BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_scores_team ON game_scores(team_id);

-- ---------------------------------------------------------------------
-- 10b. TEAM_VIEW_ACKS (live tracking of client views of results)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_view_acks (
    ack_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    team_id     UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    round_id    UUID,
    view_type   VARCHAR(50) NOT NULL,
    viewed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_team_view_ack UNIQUE (session_id, team_id, view_type, round_id)
);

CREATE INDEX IF NOT EXISTS idx_team_view_acks_session ON team_view_acks(session_id);
CREATE INDEX IF NOT EXISTS idx_team_view_acks_team ON team_view_acks(team_id);

-- =====================================================================
-- GAME 1 — MINDMAZE  (5 rounds)
-- =====================================================================
CREATE TABLE IF NOT EXISTS mindmaze_rounds (
    round_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    round_number    SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
    start_time      TIMESTAMPTZ,
    deadline        TIMESTAMPTZ,
    UNIQUE (session_id, round_number)
);

CREATE TABLE IF NOT EXISTS mindmaze_results (
    result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id            UUID NOT NULL REFERENCES mindmaze_rounds(round_id) ON DELETE CASCADE,
    team_id             UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    moves               INT NOT NULL CHECK (moves >= 0),
    mistakes            INT NOT NULL CHECK (mistakes >= 0),
    correct_tiles       INT NOT NULL CHECK (correct_tiles >= 0),
    completion_time     INTERVAL,
    round_score         NUMERIC(8,2) NOT NULL DEFAULT 0,   -- points earned this round
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_mm_results_team ON mindmaze_results(team_id);

CREATE OR REPLACE FUNCTION fn_score_mindmaze_result()
RETURNS TRIGGER AS $$
BEGIN
    NEW.round_score := GREATEST(
        0,
        (NEW.correct_tiles * 1.0) - (NEW.mistakes * 0.5)
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mm_score ON mindmaze_results;
CREATE TRIGGER trg_mm_score
BEFORE INSERT ON mindmaze_results
FOR EACH ROW EXECUTE FUNCTION fn_score_mindmaze_result();

-- =====================================================================
-- GAME 1B — ACE OF SPADES  (5 rounds)
-- Memory-recall game: 8 cards (suit + number) are shown then hidden, 2
-- decoy cards are mixed in, and the team taps cards back in the order
-- they memorised them. Scored client-side (self-reported, same trust
-- model as MindMaze) and bounds-checked server-side.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ace_spade_rounds (
    round_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    round_number    SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
    start_time      TIMESTAMPTZ,
    deadline        TIMESTAMPTZ,
    UNIQUE (session_id, round_number)
);

CREATE TABLE IF NOT EXISTS ace_spade_results (
    result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id            UUID NOT NULL REFERENCES ace_spade_rounds(round_id) ON DELETE CASCADE,
    team_id             UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    moves               INT NOT NULL CHECK (moves >= 0),
    wrong_picks         INT NOT NULL CHECK (wrong_picks >= 0),
    correct_picks       INT NOT NULL CHECK (correct_picks >= 0),
    completion_time     INTERVAL,
    round_score         NUMERIC(8,2) NOT NULL DEFAULT 0,   -- points earned this round
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (round_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_as_results_team ON ace_spade_results(team_id);

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

DROP TRIGGER IF EXISTS trg_as_score ON ace_spade_results;
CREATE TRIGGER trg_as_score
BEFORE INSERT ON ace_spade_results
FOR EACH ROW EXECUTE FUNCTION fn_score_ace_spade_result();

-- =====================================================================
-- GAME 2 — KING OF DIAMONDS  (5 rounds)
-- =====================================================================
CREATE TABLE IF NOT EXISTS king_diamond_rounds (
    round_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id              UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    round_number            SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
    start_time              TIMESTAMPTZ,
    deadline                TIMESTAMPTZ,
    average_value           NUMERIC(8,4),
    target_value            NUMERIC(8,4),          -- average * 0.8
    winner_submission_id    UUID,                   -- FK added below (submissions must exist first)
    is_closed               BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (session_id, round_number)
);

CREATE TABLE IF NOT EXISTS king_diamond_submissions (
    submission_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id            UUID NOT NULL REFERENCES king_diamond_rounds(round_id) ON DELETE CASCADE,
    team_id             UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    submitted_number    NUMERIC(6,2) NOT NULL CHECK (submitted_number BETWEEN 0 AND 100),
    submitted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),   -- server-generated, never client input
    is_valid             BOOLEAN NOT NULL DEFAULT TRUE,         -- FALSE if past deadline
    difference           NUMERIC(8,4),                          -- filled when round closes
    rank                 SMALLINT,
    round_score          NUMERIC(8,2) NOT NULL DEFAULT 0,       -- points earned this round
    is_winner            BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (round_id, team_id)
);

DO $$ BEGIN
    ALTER TABLE king_diamond_rounds
        ADD CONSTRAINT fk_kd_winner_submission
        FOREIGN KEY (winner_submission_id) REFERENCES king_diamond_submissions(submission_id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS idx_kd_sub_team ON king_diamond_submissions(team_id);

CREATE OR REPLACE FUNCTION fn_kd_validate_submission()
RETURNS TRIGGER AS $$
DECLARE
    v_deadline TIMESTAMPTZ;
BEGIN
    SELECT deadline INTO v_deadline FROM king_diamond_rounds WHERE round_id = NEW.round_id;
    -- Unified grace period of 30 seconds (matches game_auth.py grace period across all games)
    IF v_deadline IS NOT NULL AND NEW.submitted_at > (v_deadline + INTERVAL '30 seconds') THEN
        NEW.is_valid := FALSE;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kd_validate ON king_diamond_submissions;
CREATE TRIGGER trg_kd_validate
BEFORE INSERT ON king_diamond_submissions
FOR EACH ROW EXECUTE FUNCTION fn_kd_validate_submission();

CREATE OR REPLACE FUNCTION fn_close_king_diamond_round(p_round_id UUID)
RETURNS VOID AS $$
DECLARE
    v_avg    NUMERIC(8,4);
    v_target NUMERIC(8,4);
BEGIN
    SELECT AVG(submitted_number) INTO v_avg
      FROM king_diamond_submissions
     WHERE round_id = p_round_id AND is_valid = TRUE;

    v_avg    := COALESCE(v_avg, 0);
    v_target := v_avg * 0.8;

    UPDATE king_diamond_rounds
       SET average_value = v_avg,
           target_value  = v_target,
           is_closed     = TRUE
     WHERE round_id = p_round_id;

    UPDATE king_diamond_submissions
       SET difference = ABS(submitted_number - v_target)
     WHERE round_id = p_round_id AND is_valid = TRUE;

    WITH ranked AS (
        SELECT submission_id,
               DENSE_RANK() OVER (ORDER BY difference ASC) AS rnk
          FROM king_diamond_submissions
         WHERE round_id = p_round_id AND is_valid = TRUE
    )
    UPDATE king_diamond_submissions ks
       SET rank        = r.rnk,
           is_winner   = (r.rnk = 1),
           round_score = CASE 
                           WHEN r.rnk <= 1 THEN 0.0
                           ELSE (0.25 * (r.rnk - 1) * (r.rnk + 2))::NUMERIC(8,2)
                         END
      FROM ranked r
     WHERE ks.submission_id = r.submission_id;

    UPDATE king_diamond_submissions
       SET round_score = 20.0,  -- Full penalty for non-submitter (matches king_diamond_base_points config)
           rank = NULL,
           difference = NULL,
           is_winner = FALSE
     WHERE round_id = p_round_id AND is_valid = FALSE;

    UPDATE king_diamond_rounds
       SET winner_submission_id = (
           SELECT submission_id FROM king_diamond_submissions
            WHERE round_id = p_round_id AND is_winner = TRUE LIMIT 1
       )
     WHERE round_id = p_round_id;
END;
$$ LANGUAGE plpgsql;

-- =====================================================================
-- GAME 3 — JACK OF HEARTS  (5 rounds)
-- =====================================================================

CREATE TABLE IF NOT EXISTS jh_symbols (
    symbol_id   SMALLSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL,
    suit        TEXT,
    rank        TEXT
);

INSERT INTO jh_symbols (symbol_id, code, label, suit, rank) VALUES
    -- Spades ♠
    (1, 'SPADE_A', '♠ A', 'SPADE', 'A'),
    (2, 'SPADE_2', '♠ 2', 'SPADE', '2'),
    (3, 'SPADE_3', '♠ 3', 'SPADE', '3'),
    (4, 'SPADE_4', '♠ 4', 'SPADE', '4'),
    (5, 'SPADE_5', '♠ 5', 'SPADE', '5'),
    (6, 'SPADE_6', '♠ 6', 'SPADE', '6'),
    (7, 'SPADE_7', '♠ 7', 'SPADE', '7'),
    (8, 'SPADE_8', '♠ 8', 'SPADE', '8'),
    (9, 'SPADE_9', '♠ 9', 'SPADE', '9'),
    (10, 'SPADE_10', '♠ 10', 'SPADE', '10'),
    -- Hearts ♥
    (11, 'HEART_A', '♥ A', 'HEART', 'A'),
    (12, 'HEART_2', '♥ 2', 'HEART', '2'),
    (13, 'HEART_3', '♥ 3', 'HEART', '3'),
    (14, 'HEART_4', '♥ 4', 'HEART', '4'),
    (15, 'HEART_5', '♥ 5', 'HEART', '5'),
    (16, 'HEART_6', '♥ 6', 'HEART', '6'),
    (17, 'HEART_7', '♥ 7', 'HEART', '7'),
    (18, 'HEART_8', '♥ 8', 'HEART', '8'),
    (19, 'HEART_9', '♥ 9', 'HEART', '9'),
    (20, 'HEART_10', '♥ 10', 'HEART', '10'),
    -- Diamonds ♦
    (21, 'DIAMOND_A', '♦ A', 'DIAMOND', 'A'),
    (22, 'DIAMOND_2', '♦ 2', 'DIAMOND', '2'),
    (23, 'DIAMOND_3', '♦ 3', 'DIAMOND', '3'),
    (24, 'DIAMOND_4', '♦ 4', 'DIAMOND', '4'),
    (25, 'DIAMOND_5', '♦ 5', 'DIAMOND', '5'),
    (26, 'DIAMOND_6', '♦ 6', 'DIAMOND', '6'),
    (27, 'DIAMOND_7', '♦ 7', 'DIAMOND', '7'),
    (28, 'DIAMOND_8', '♦ 8', 'DIAMOND', '8'),
    (29, 'DIAMOND_9', '♦ 9', 'DIAMOND', '9'),
    (30, 'DIAMOND_10', '♦ 10', 'DIAMOND', '10'),
    -- Clubs ♣
    (31, 'CLUB_A', '♣ A', 'CLUB', 'A'),
    (32, 'CLUB_2', '♣ 2', 'CLUB', '2'),
    (33, 'CLUB_3', '♣ 3', 'CLUB', '3'),
    (34, 'CLUB_4', '♣ 4', 'CLUB', '4'),
    (35, 'CLUB_5', '♣ 5', 'CLUB', '5'),
    (36, 'CLUB_6', '♣ 6', 'CLUB', '6'),
    (37, 'CLUB_7', '♣ 7', 'CLUB', '7'),
    (38, 'CLUB_8', '♣ 8', 'CLUB', '8'),
    (39, 'CLUB_9', '♣ 9', 'CLUB', '9'),
    (40, 'CLUB_10', '♣ 10', 'CLUB', '10')
ON CONFLICT (symbol_id) DO UPDATE
SET code = EXCLUDED.code,
    label = EXCLUDED.label,
    suit = EXCLUDED.suit,
    rank = EXCLUDED.rank;

CREATE TABLE IF NOT EXISTS jack_heart_rounds (
    round_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES game_sessions(session_id) ON DELETE CASCADE,
    round_number    SMALLINT NOT NULL CHECK (round_number BETWEEN 1 AND 5),
    start_time      TIMESTAMPTZ,
    deadline        TIMESTAMPTZ,
    UNIQUE (session_id, round_number)
);

CREATE TABLE IF NOT EXISTS jack_heart_assignments (
    assignment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id        UUID NOT NULL REFERENCES jack_heart_rounds(round_id) ON DELETE CASCADE,
    team_id         UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    symbol_id       SMALLINT NOT NULL REFERENCES jh_symbols(symbol_id),
    UNIQUE (round_id, team_id),      -- every team has exactly one symbol
    UNIQUE (round_id, symbol_id)     -- no two teams share a symbol (bijective)
);

CREATE TABLE IF NOT EXISTS jack_heart_answers (
    answer_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id                UUID NOT NULL REFERENCES jack_heart_rounds(round_id) ON DELETE CASCADE,
    team_id                 UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    submitted_symbol_id     SMALLINT NOT NULL REFERENCES jh_symbols(symbol_id),
    actual_symbol_id        SMALLINT NOT NULL REFERENCES jh_symbols(symbol_id),  -- filled by trigger
    is_correct               BOOLEAN GENERATED ALWAYS AS (submitted_symbol_id = actual_symbol_id) STORED,
    round_score              NUMERIC(8,2) NOT NULL DEFAULT 0,   -- points earned this round
    submitted_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    time_taken                INTERVAL,
    UNIQUE (round_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_jh_ans_team ON jack_heart_answers(team_id);

-- Never trust actual_symbol_id from the client: pull it server-side
-- from the team's own (hidden-from-them) assignment.
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

DROP TRIGGER IF EXISTS trg_jh_validate ON jack_heart_answers;
CREATE TRIGGER trg_jh_validate
BEFORE INSERT ON jack_heart_answers
FOR EACH ROW EXECUTE FUNCTION fn_validate_jh_answer();

-- =====================================================================
-- ROOM RESULTS & QUALIFICATION
-- =====================================================================
CREATE TABLE IF NOT EXISTS room_results (
    result_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id              UUID NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    team_id              UUID NOT NULL REFERENCES teams(team_id) ON DELETE CASCADE,
    mindmaze_score       NUMERIC(8,2) NOT NULL DEFAULT 0,
    ace_spade_score      NUMERIC(8,2) NOT NULL DEFAULT 0,
    king_diamond_score   NUMERIC(8,2) NOT NULL DEFAULT 0,
    jack_heart_score     NUMERIC(8,2) NOT NULL DEFAULT 0,
    total_score          NUMERIC(9,2) GENERATED ALWAYS AS
                             (mindmaze_score + ace_spade_score + king_diamond_score + jack_heart_score) STORED,
    rank                 SMALLINT,
    is_qualified         BOOLEAN NOT NULL DEFAULT FALSE,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (room_id, team_id)
);

CREATE INDEX IF NOT EXISTS idx_room_results_room ON room_results(room_id);

-- Configurable "top N qualify" instead of hard-coding it.
-- room_id = NULL means "applies to every room in this round" (default rule).
CREATE TABLE IF NOT EXISTS qualification_rules (
    rule_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id    UUID NOT NULL REFERENCES rounds(round_id) ON DELETE CASCADE,
    room_id     UUID REFERENCES rooms(room_id),
    top_n       SMALLINT NOT NULL CHECK (top_n > 0),
    UNIQUE (round_id, room_id)
);

-- Recomputes room_results for one room from the current game_scores,
-- re-ranks, and applies the room's (or round's default) qualification rule.
CREATE OR REPLACE FUNCTION fn_compute_room_results(p_room_id UUID)
RETURNS VOID AS $$
DECLARE published_games_count INT;
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

    -- Get count of published games for this room
    SELECT COUNT(DISTINCT g.code) INTO published_games_count
    FROM game_sessions gs
    JOIN games g ON g.game_id = gs.game_id
    WHERE gs.room_id = p_room_id AND gs.is_published IS TRUE;

    -- Only set is_qualified when ALL 4 games are published; reset to FALSE otherwise
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
        -- Reset is_qualified to FALSE if not all games published yet
        UPDATE room_results rr
           SET is_qualified = FALSE
         WHERE rr.room_id = p_room_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_teams_touch ON teams;
CREATE TRIGGER trg_teams_touch  BEFORE UPDATE ON teams       FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();

DROP TRIGGER IF EXISTS trg_scores_touch ON game_scores;
CREATE TRIGGER trg_scores_touch BEFORE UPDATE ON game_scores FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at();

-- ---------------------------------------------------------------------
-- Remaining indexes
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_selections_team ON round1_selections(team_id);
CREATE INDEX IF NOT EXISTS idx_selections_room ON round1_selections(room_id);

-- =====================================================================
-- LIVE LEADERBOARD VIEW
-- =====================================================================
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

-- =====================================================================
-- OVERALL (CROSS-ROOM) SCOREBOARD
-- =====================================================================
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

-- Per-game scoreboard across all rooms (e.g. "best MindMaze runs overall").
CREATE OR REPLACE VIEW v_game_leaderboard AS
SELECT
    g.code AS game_code,
    g.name AS game_name,
    r.room_code,
    t.team_code,
    t.team_name,
    gs_score.score,
    RANK() OVER (PARTITION BY g.game_id ORDER BY gs_score.score DESC) AS game_rank
FROM game_scores gs_score
JOIN game_sessions se ON se.session_id = gs_score.session_id
JOIN games g ON g.game_id = se.game_id
JOIN rooms r ON r.room_id = se.room_id
JOIN teams t ON t.team_id = gs_score.team_id;

-- COMMIT;

-- =====================================================================
-- EXAMPLE SETUP (uncomment / adapt to bootstrap a run)
-- =====================================================================
-- INSERT INTO rounds (round_number, name, status)
-- VALUES (1, 'Card Games', 'ACTIVE');
--
-- INSERT INTO rooms (round_id, room_number, room_code)
-- SELECT round_id, n, 'R' || LPAD(n::TEXT, 2, '0')
--   FROM rounds, generate_series(1,10) AS n
--  WHERE round_number = 1;
--
-- INSERT INTO round_games (round_id, game_id, game_order)
-- SELECT rd.round_id, g.game_id,
--        CASE g.code WHEN 'MINDMAZE' THEN 1 WHEN 'ACE_SPADE' THEN 2 WHEN 'KING_DIAMOND' THEN 3 WHEN 'JACK_HEART' THEN 4 END
--   FROM rounds rd CROSS JOIN games g
--  WHERE rd.round_number = 1;
--
-- INSERT INTO game_sessions (round_id, room_id, game_id)
-- SELECT rd.round_id, rm.room_id, rg.game_id
--   FROM rounds rd
--   JOIN rooms rm ON rm.round_id = rd.round_id
--   JOIN round_games rg ON rg.round_id = rd.round_id
--  WHERE rd.round_number = 1;
