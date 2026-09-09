# Round 1 Backend

FastAPI backend for the Round 1 card-game event schema (`sql/round1_schema.sql`).
Implements the design in `round1_backend_design.md`: async FastAPI + SQLAlchemy,
JWT auth for teams and admins, deadline-driven round/session/room roll-ups via
APScheduler, and a Redis-backed live-leaderboard WebSocket.

## Stack

FastAPI · SQLAlchemy 2.0 (async) + asyncpg · Alembic · Pydantic v2 ·
python-jose + passlib (JWT/bcrypt) · APScheduler · Redis · pytest.

## Project layout

```
app/
├── main.py            # FastAPI app, router includes, scheduler lifespan
├── core/               # config, JWT/password security, exception mapping
├── db/                 # async engine/session, declarative base
├── models/              # SQLAlchemy ORM models, mirrors sql/round1_schema.sql
├── schemas/             # Pydantic request/response models
├── api/v1/               # routers (thin) — auth, teams, rounds, selection,
│                          # sessions, mindmaze, king_diamond, jack_heart,
│                          # leaderboard, admin, admin_data, demo
├── services/             # business logic per domain
├── workers/              # APScheduler setup + close_round/session/room jobs
└── ws/                   # WebSocket scoreboard + Redis pub/sub bridge
alembic/                  # migrations; 0001 applies sql/round1_schema.sql as-is
sql/                       # the raw schema SQL (source of truth for triggers/views)
tests/                     # pytest + httpx.AsyncClient against a real Postgres
frontend/                  # static team-app / admin-app / shared JS+CSS, served
                            # directly by FastAPI (see "Frontend" below)
```

## Frontend

`frontend/` (team-app, admin-app, shared) is plain HTML/CSS/JS with no build
step. `app/main.py` mounts it directly on the same FastAPI app once it detects
the folder at startup:

| URL              | Serves                                    |
|------------------|--------------------------------------------|
| `/`              | redirects to `/team-app/`                   |
| `/team`          | redirects to `/team-app/`                   |
| `/admin`         | redirects to `/admin-app/`                  |
| `/team-app/`     | `frontend/team-app/index.html` + assets     |
| `/admin-app/`    | `frontend/admin-app/index.html` + assets    |
| `/shared/`       | `frontend/shared/` (shared css/js/assets)   |
| `/api/v1/...`    | the REST API                                |
| `/ws/...`        | the leaderboard WebSocket                   |

Because the frontend now lives inside this same project, `docker compose up
--build` (and the plain `Dockerfile`) picks it up automatically — there's
nothing extra to build or copy. The frontend's API client (`frontend/shared/js/api.js`)
defaults to `window.location.origin`, so it talks to whichever host/port the
API is served on without any config.

## Running locally

```bash
cp .env.example .env   # edit JWT_SECRET at minimum
docker compose up --build
```

This starts Postgres, Redis, and the API on `http://localhost:8000`
(interactive docs at `/docs`). The API container runs its own in-process
scheduler (see `app/main.py`'s lifespan hook), so a session started via
`POST /admin/rooms/{room_id}/sessions/{game_code}/start` will auto-close its
rounds without any manual step.

Apply migrations (first run applies `sql/round1_schema.sql` verbatim):

```bash
docker compose exec api alembic upgrade head
```

## Running without Docker

```bash
pip install -e ".[dev]"
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Requires a local Postgres 16+ and Redis reachable at the URLs in `.env`.

## Auth

Two independent JWT flows:

- `POST /api/v1/auth/team/login` — `{team_code, password}` → JWT with team's
  identity. Every subsequent team endpoint takes `team_id` only from this
  token, never from the request body.
- `POST /api/v1/auth/admin/login` — `{username, password}` → JWT carrying the
  admin's role (`SUPER_ADMIN` / `ROOM_ADMIN`). `SUPER_ADMIN`-only endpoints
  are marked in the routers via `require_role(...)`.

The first `SUPER_ADMIN` is seeded by `app/db/seed_admin.py`, which
`entrypoint.sh` runs when `RUN_MIGRATIONS=true` (credentials from
`ADMIN_USERNAME` / `ADMIN_PASSWORD`, defaulting to `admin` / `admin123` —
change them before a real event). Teams come from the spreadsheet import
below.

## Team registration by spreadsheet

Teams don't have to be created one at a time. **Teams → Import from Sheet**
in the admin console takes the registration sheet the event already
collects (a Google Form export, a shared `.xlsx`, a `.csv`) and turns it
into ready-to-play accounts:

| Field | Where it comes from |
|-------|---------------------|
| `team_code` | generated: `B@GCEE-` + 4 random digits + `#`, e.g. `B@GCEE-7391#` |
| `password` | the **first 4 digits of the team leader's phone number** |
| `team_name` | the sheet |
| `leader_name` / `leader_phone` / `leader_email` | the sheet (migration `0010`) |

Columns are matched by **header name, not position**, so an existing form
export usually imports as-is; a `Timestamp` column or a title banner above
the table is ignored. `+91 98765 43210` and `98765 43210` both derive the
password `9876` — a number longer than 10 digits is trimmed to its last 10
first, so the password is never the country code. If auto-detection can't
find a column, the modal asks for it.

The import is **two calls on purpose**:

```
POST /admin/teams/import/preview   # parses, validates, writes NOTHING
POST /admin/teams/import           # creates the reviewed rows, one transaction
```

The preview reports the real code and password for every row plus a
per-row status (`OK`, `MISSING_TEAM_NAME`, `INVALID_PHONE`,
`DUPLICATE_IN_FILE`, `DUPLICATE_IN_DB`, `OVER_CAPACITY`), and the admin
confirms row by row. A half-imported roster 20 minutes before an event is
the failure this exists to prevent. Duplicate detection is
whitespace-collapsed and case-insensitive — the DB's `UNIQUE(team_name)`
would happily accept both "Dragon Warriors" and "Dragon  Warriors", which
is exactly the pair you don't want on a roster.

Two more endpoints round it out:

- `GET /admin/teams/import/template` — a blank sheet in the expected shape.
- `POST /admin/teams/credentials-export` — the login sheet to hand out.
  It takes the import's response back rather than re-reading the database,
  because that response is the only place the passwords exist in the clear.

The 40-team cap (`trg_team_cap`) is still enforced by the database; the
preview only warns about it early.

## Exporting the Round 2 qualifiers

**Export Round 2 Qualifiers** on the dashboard (and on any round's page)
produces the winners list as a shareable `.xlsx`:

```
GET /admin/rounds/{round_id}/winners          # the same data as JSON
GET /admin/rounds/{round_id}/winners/export   # the .xlsx
```

Both re-run `fn_compute_room_results` for every room in the round first
(`?recompute=false` to skip it), so a score corrected minutes earlier is
always reflected — this is a document people act on. Nothing here decides
who qualified: `is_qualified` is written by that function applying the
round's own `qualification_rules.top_n`, so changing the qualification rule
and re-exporting is the supported way to change the list.

The workbook has two sheets:

- **Round 2 Qualifiers** — only the qualifying teams, re-seeded by total
  score *across every room* (the order Round 2 needs), with each team's
  leader name, phone and email so they can actually be contacted.
- **All Teams** — the full standings by room, qualifiers highlighted, so
  the file answers "why isn't my team on the list?" on its own.

## Design notes carried over from the schema

- **The DB is the source of truth for "once only" rules.** The API does not
  pre-check "has this team already selected" or "has this team already
  submitted" — it attempts the insert and lets `UNIQUE` constraints /
  triggers raise, then maps that to a clean `409` in
  `app/core/exceptions.py`.
- **Jack of Hearts' visible-symbols filter is 100% API-side** — nothing in
  the schema hides a team's own symbol automatically. See
  `app/services/jack_heart_service.get_visible_symbols` and the
  (placeholder) regression test in `tests/test_jack_heart.py`.
- **Server-generated fields are never accepted from the client**:
  `submitted_at`, `room_id` (selection), `actual_symbol_id` (Jack of
  Hearts) are all filled by DB defaults/triggers.
- **The results schema is scoped to exactly three named games**
  (`room_results` / `v_room_leaderboard` / `v_overall_leaderboard` in
  `sql/round1_schema.sql` have fixed `mindmaze_score` / `king_diamond_score`
  / `jack_heart_score` columns). `PUT /admin/rounds/{round_id}/games`
  configures which *subset* of MindMaze / King of Diamonds / Jack of Hearts
  runs in a round — it deliberately can't add a fourth game
  (`admin_service.replace_game_lineup` rejects unknown codes, and
  `app/workers/jobs.py::_maybe_close_room` compares against the actual
  configured lineup size rather than a hardcoded 3). Making the schema
  fully game-count-agnostic (a generic `game_scores`-driven leaderboard, or
  a dynamic pivot) was considered and deferred as a larger, separate change
  — see the audit for the trade-off.
- **A game session's roster is snapshotted at start time**
  (`game_sessions.roster_team_ids`, set in `session_service.start_session`).
  Round-close roll-ups (`app/workers/jobs.py`) use this snapshot — not a
  live query against `round1_selections` — as the source of truth for
  "which teams should have a score row", so a team moved between rooms
  mid-event (blocked once a session has started; see
  `admin_service.move_team_room`) can't desync a room's roster from what an
  already-running session expects.
- **Demo (practice) rounds never touch the database.** Each of the three
  games has a practice twin that an admin arms per round
  (`POST /admin/rounds/{round_id}/demo/{game_code}/start`) and can replay as
  often as a room needs (`.../restart` — "Practice Again"). While one is
  live it takes over the team screens for that game, behind a practice
  banner; `.../end` hands them straight back to the real session. Every
  piece of demo state — sub-rounds, deadlines, submissions, Jack of Hearts
  card assignments, ranks and points — lives in Redis under the `demo:` key
  prefix with a 12h TTL, so a practice round cannot write to `game_scores`,
  `mindmaze_results`, `king_diamond_submissions`, `jack_heart_answers`,
  `room_results` or any leaderboard view. The only SQL
  `app/services/demo_service.py` issues is read-only (which rooms are in a
  round, who is in a room, the `jh_symbols` deck); a regression test asserts
  the module contains no write at all. See "Demo (practice) rounds" below.
- **ROOM_ADMIN accounts are bound to a single room** via the nullable
  `admins.room_id` column (`app/api/deps.py::assert_admin_room_access`).
  NULL means unrestricted — true for every `SUPER_ADMIN`, and, for backward
  compatibility, for a `ROOM_ADMIN` account that hasn't been assigned a
  room yet via `PATCH /admin/admins/{admin_id}/room`. Assign one to every
  real `ROOM_ADMIN` account before an event to actually get the per-room
  boundary; an unassigned one is equivalent to today's unrestricted
  behavior.
- **Round-wide control** (`POST /admin/rounds/{round_id}/sessions/{game_code}
  /{start,pause,resume,restart,force-complete}`, `SUPER_ADMIN`-only) fans a
  single-room action out across every room in the round whose configured
  lineup includes that game, each room getting its own DB transaction so
  one room's failure can't roll back another's success. It reuses the
  existing single-room functions in `app/services/session_service.py`
  unchanged, so per-room control (e.g. for adjudication) still works
  exactly as before. `GET /admin/scheduler/jobs/by-round/{round_id}/
  {game_code}` shows which close-jobs a round-wide pause/stop would cancel,
  before it does it.

## Demo (practice) rounds

Every game can be rehearsed before it counts. From a round's admin page,
each game card carries a **Practice Round** panel:

| Control              | Effect                                                                 |
|----------------------|------------------------------------------------------------------------|
| Start Demo           | Arms a practice run in every room in the round whose lineup has that game |
| Practice Again       | Discards the attempt and deals a fresh one — works from any state        |
| Pause / Resume Demo  | Same semantics as a real session; resume gives back the paused time       |
| Start / Replay sub-round | Per-sub-round control, mirroring the real sub-round buttons          |
| End Demo             | Tears the practice surface down; team screens return to the real game    |

Teams play on the **real game screens** — same board, same timers, same
reveal animations — with an amber practice banner pinned under the header
and a "this score is not recorded" note on every screen that reports a
score. The team app picks the practice endpoints over the real ones simply
by being handed `api.demo` instead of `api.team` (`shell.js` decides;
`gameApi(ctx)` in each game screen consumes it), so the two paths cannot
drift.

**Nothing scored in a demo is persisted.** The whole surface lives in Redis:

```
demo:s:{round_id}:{GAME}:{room_id}   # the session blob (sub-rounds, results)
demo:sub:{demo_round_id}             # HASH team_id -> submission
demo:asg:{demo_round_id}             # HASH team_id -> Jack of Hearts card
demo:r:{demo_round_id}               # reverse index -> owning session key
```

all with a 12h TTL, so an abandoned demo evaporates on its own. Sub-rounds
close lazily — on the next read, or as soon as the whole room has submitted
— rather than through APScheduler, whose jobs are DB-writing by
construction and whose job store would outlive the practice run.

Scoring reuses the real games' pure helpers
(`mindmaze_service.compute_round_score`,
`king_diamond_service._round_score_for_rank`,
`jack_heart_service.compute_round_score`), so a practice sub-round is scored
by exactly the rules the real one would be — the numbers are just thrown
away with the key.

`docker compose` already runs Redis, so there is nothing extra to configure;
if Redis is unavailable the demo endpoints fail and the real game is
untouched.

## Testing

```bash
pytest
```

`tests/test_team_import.py` needs no Postgres either — the spreadsheet
importer's column detection, phone normalisation, team-code format and
row validation are pure functions, and the two exports are checked by
building a workbook and reading it back. It also asserts the blank import
template survives its own round trip through the importer.

`tests/test_demo_rounds.py` is the other part of the suite that needs **no
Postgres** — a practice round only touches Redis, so it runs against
`fakeredis` with the three read-only DB lookups stubbed. It covers the
lifecycle (start / restart / pause / resume / per-sub-round replay / end),
score parity with each real game, the Jack of Hearts "never reveal your own
card" rule, and a guard asserting `demo_service` contains no database write.

Tests are integration-first against a real Postgres with the actual schema
applied (`tests/conftest.py`) — the triggers and constraints are half the
business logic, so a mocked DB session would test nothing. Set
`TEST_DATABASE_URL` to point at a throwaway database. The King of Diamonds
and Jack of Hearts priority tests are stubbed with `pytest.skip(...)` pending
seed fixtures for a round/session/assignment — wire those up against your
own seed data before relying on them.

## What's still a stub / needs hardening before a real event

- No seed script for the first admin account or bootstrap round — see the
  commented `EXAMPLE SETUP` block at the bottom of `sql/round1_schema.sql`.
- `RANK_POINTS` in `app/services/king_diamond_service.py` is a placeholder
  scoring scale — tune it to your event's actual rules.
- The default `MemoryJobStore` for APScheduler doesn't survive an API
  restart mid-event; swap for `RedisJobStore` (commented pointer in
  `app/workers/scheduler.py`) before a real run with the `worker` service
  taking over standalone.
- `tests/test_king_diamond.py` and `tests/test_jack_heart.py` need real
  fixtures (a seeded round/room/session) to actually run rather than skip.
- Run `alembic upgrade head` before a real event to pick up
  `0004_room_admin_binding_and_roster_snapshot` — sessions started before
  that migration won't have a `roster_team_ids` snapshot, so their
  round-close roll-up falls back to only scoring teams that actually have a
  score row (the old behavior), not the full roster.
- `admin_service.replace_game_lineup` only accepts MINDMAZE / KING_DIAMOND /
  JACK_HEART — see the "results schema is scoped to exactly three named
  games" design note above before trying to add a fourth game.
