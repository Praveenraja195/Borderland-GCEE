# Borderland-GCEE — Frontend

Two static, framework-free web apps for the Round 1 event, built to
`THEME_GUIDE.md` and wired against every endpoint in
`borderland-api-reference.md`:

- **`team-app/`** — what teams use on their phones: login, suit/number
  selection, waiting room, dark "card back" home hub, the three games
  (MindMaze, King of Diamonds, Jack of Hearts), and a live leaderboard.
- **`admin-app/`** — the run-of-show console: rounds, game lineup editor,
  room/session control (start / pause / resume / restart / force-complete),
  teams CRUD, admin accounts (SUPER_ADMIN), and a scheduler debug panel.
- **`shared/`** — the design-token stylesheet (`theme.css`), the REST/WS
  clients, the bilingual copy dictionary, and the suit-glyph SVGs. Both apps
  import from here — nothing is duplicated between them.

No build step. No `npm install`. Open `team-app/index.html` /
`admin-app/index.html` directly, or serve the folder statically:

```bash
cd borderland-frontend
python3 -m http.server 8080
# then visit http://localhost:8080/team-app/  and  /admin-app/
```

Everything is plain ES modules + hand-written CSS, so any static host
(nginx, Netlify, S3, GitHub Pages) works as-is.

## Pointing it at your backend

Neither app has a hardcoded API host. On first load, use the **Settings**
link on the team login screen (or the API Host field on the admin login
screen) to set your backend's base URL, e.g. `https://your-host/api/v1`.
It's saved to `localStorage` and reused on every request; the WebSocket
host is derived from it automatically (swaps `http(s)` → `ws(s)`, drops the
`/api/v1` suffix, appends `/ws`).

## The one deliberate workaround: §6.4 of the API reference

The API reference calls out that **no team-facing endpoint currently
returns a game's live `round_id` or its `deadline`** — the team only
learns a round exists once it starts polling/submitting, or a 409 tells it
the round already closed. Rather than paper over that, the team app
surfaces it: when a game session is `IN_PROGRESS`, the team is asked to
enter the round ID (and optional deadline) an admin relays via the room's
screen or a QR code, exactly as the reference doc suggests as a stopgap.
That value is cached per `session_id` (in `team-app/js/round-context.js`)
so it resets automatically the next time an admin restarts the session.

**Delete this whole affordance in one place** once the backend ships either
of the two fixes the reference doc proposes (a `GET .../rounds/current`
endpoint, or including `round_id`/`deadline` in `GET /rooms/{id}/sessions`):
swap the `getRoundContext(...)` call in `team-app/js/screens/games/shell.js`
for a real API call and delete `round-context.js`.

Similarly, there's no team-facing "what round is Round 1 event using
right now" endpoint either, so the **team Settings screen** has a manual
Round ID field for that top-level round (used by the suit/number selection
call). Same story — swap it out once that's exposed.

## Theme notes

`shared/css/theme.css` implements `THEME_GUIDE.md` literally: the palette,
the two-tier bilingual label pattern, `【bracket】` headers, hairline form
fields, the full-width black CTA, the giant digital countdown, and the
dark-mode diamond bottom nav are all there as reusable classes — no screen
reimplements them from scratch. Suit glyphs are flat inline SVG (not
skeuomorphic cards) per the guide, except the card-back JPGs (compressed
from your two uploaded reference images) used as the dark-mode background.

The admin console intentionally stays in **light/functional mode
throughout** — the guide reserves the dark "world" mode for the team home
hub, and an admin console is inherently administrative/data-dense.

Fonts (Oswald, Inter, Noto Sans JP, JetBrains Mono, UnifrakturMaguntia for
the wordmark) load from Google Fonts via `@import` in `theme.css` — swap
for self-hosted files if the event venue won't have outbound internet.

## Known simplifications

- **Team registration**: there's still no team self-registration endpoint —
  teams are created by an admin. In practice that's the **Teams → Import
  from Sheet** flow (`admin-app/js/screens/team-import.js`), which reads the
  event's registration spreadsheet and creates every account at once; the
  single-team "New team" modal remains for one-offs. The 【チーム登録】 header
  from the theme guide lives on those admin screens rather than a
  team-facing one.
- Error `detail` strings are shown in English by default, with a small
  lookup table (`shared/js/copy.js` → `ERROR_JP`) translating the two
  messages named in the theme guide; extend that table as
  `app/core/exceptions.py` grows.
- MindMaze's grid, timing, and lit-tile count are entirely frontend-owned,
  as the reference doc specifies — tune `GRID_SIZE`/`DISPLAY_MS`/`litCount`
  in `team-app/js/screens/games/mindmaze.js` to taste.
