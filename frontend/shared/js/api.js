// Shared REST client for both team-app and admin-app.
// Base URL is configurable at runtime (Settings screen) since the backend
// host isn't known at build time; it's kept in localStorage.

const DEFAULT_BASE = typeof window !== 'undefined' && window.location && window.location.origin
  ? `${window.location.origin}/api/v1`
  : '/api/v1';

export function getApiBase() {
  const saved = localStorage.getItem('bl_api_base');
  if (!saved || saved.includes('example.com')) {
    return DEFAULT_BASE;
  }
  return saved;
}

export function setApiBase(url) {
  localStorage.setItem('bl_api_base', url.replace(/\/+$/, ''));
}

export function getWsBase() {
  const api = getApiBase();
  // swap scheme http(s) -> ws(s) and strip the /api/v1 suffix
  const wsScheme = api.startsWith('https') ? 'wss' : 'ws';
  const host = api.replace(/^https?:\/\//, '').replace(/\/api\/v1\/?$/, '');
  return `${wsScheme}://${host}/ws`;
}

const TOKEN_KEY_TEAM = 'bl_team_token';
const TOKEN_KEY_ADMIN = 'bl_admin_token';

let serverTimeOffset = 0;
// True once syncServerTime has produced an RTT-compensated offset; until
// then the coarse Date-header sync in apiFetch is allowed to seed it.
let preciseTimeSynced = false;

export function setServerTimeOffset(offsetMs) {
  serverTimeOffset = offsetMs;
  preciseTimeSynced = true;
}

export function getServerTimeOffset() {
  return serverTimeOffset;
}

export function getServerNow() {
  return Date.now() + serverTimeOffset;
}

// Best sync seen recently: { offset, rtt, at }. A single /time sample can be
// off by up to half its round-trip when the network is jittery (event Wi-Fi),
// so each sync takes a few samples and trusts the one with the lowest RTT —
// the standard NTP trick. A worse sample never overrides a better recent one.
let bestSync = null;
const SYNC_SAMPLES = 3;
const SYNC_STALE_MS = 60000;
const SYNC_JITTER_MS = 15;

async function sampleServerTime() {
  const t0 = Date.now();
  const res = await fetch(`${getApiBase()}/time`, { cache: 'no-store' });
  const t1 = Date.now();
  if (!res.ok) return null;
  const data = await res.json();
  if (!data || typeof data.server_time_ms !== 'number') return null;
  const rtt = t1 - t0;
  // The server stamped its clock roughly mid-flight.
  return { offset: Math.round(data.server_time_ms + rtt / 2 - t1), rtt };
}

export async function syncServerTime(samples = SYNC_SAMPLES) {
  const taken = [];
  for (let i = 0; i < samples; i++) {
    try {
      const smp = await sampleServerTime();
      if (smp) taken.push(smp);
    } catch (_) {}
  }
  if (!taken.length) return;
  taken.sort((a, b) => a.rtt - b.rtt);
  const best = taken[0];
  const stale = !bestSync || Date.now() - bestSync.at > SYNC_STALE_MS;
  if (stale || best.rtt <= bestSync.rtt * 1.5) {
    // Ignore sub-jitter wobble so the countdown never visibly jumps.
    if (!preciseTimeSynced || Math.abs(best.offset - serverTimeOffset) > SYNC_JITTER_MS) {
      serverTimeOffset = best.offset;
    }
    preciseTimeSynced = true;
    bestSync = { ...best, at: Date.now() };
  }
}

if (typeof window !== 'undefined') {
  syncServerTime();
  setInterval(syncServerTime, 10000);
}

export function getToken(kind) {
  return localStorage.getItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM);
}
export function setToken(kind, token) {
  localStorage.setItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM, token);
}
export function clearToken(kind) {
  localStorage.removeItem(kind === 'admin' ? TOKEN_KEY_ADMIN : TOKEN_KEY_TEAM);
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * @param {string} path        e.g. '/teams/me'
 * @param {object} opts        { method, body, kind: 'team'|'admin', auth: bool, onUnauthorized }
 */
export async function apiFetch(path, opts = {}) {
  const {
    method = 'GET',
    body,
    kind = 'team',
    auth = true,
    onUnauthorized,
  } = opts;

  const headers = { 'Content-Type': 'application/json' };
  if (auth) {
    const token = getToken(kind);
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new ApiError(0, 'Could not reach the server. Check your connection or the API host in Settings.');
  }

  if (res.status === 401) {
    clearToken(kind);
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(401, 'Session expired. Please log in again.');
  }

  // Coarse clock sync from the response Date header. That header only has
  // 1-second resolution, so applying it on every response made
  // serverTimeOffset jitter by up to ±1s between fetches — visible as the
  // pre-round 3-2-1 countdown skipping or repeating a number. It is now a
  // fallback until the precise /time sync (syncServerTime, RTT-compensated)
  // has succeeded, and after that only corrects a genuine clock change
  // (> 1.5s), never sub-second header noise.
  const dateHeader = res.headers.get('date');
  if (dateHeader) {
    const serverMs = Date.parse(dateHeader);
    if (!isNaN(serverMs)) {
      const headerOffset = serverMs - Date.now();
      // Critical: reject if clock skew > 60 seconds
      if (Math.abs(headerOffset) > 60000) {
        console.error(`Critical clock skew: ${Math.abs(headerOffset) / 1000}s. Device clock may be wrong.`);
        // Don't use this offset; keep previous if available
        if (serverTimeOffset === 0) serverTimeOffset = headerOffset; // fallback if first sync
      } else if (!preciseTimeSynced) {
        // Coarse 1s-resolution fallback until the first precise /time sync;
        // never let it override a precise sync (the periodic /time sync
        // catches a genuine device clock change within 10s anyway).
        serverTimeOffset = headerOffset;
      }
    }
  }

  if (res.status === 204) return null;

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = null; }
  }

  if (!res.ok) {
    throw new ApiError(res.status, (data && data.detail) || res.statusText);
  }
  return data;
}

/**
 * Multipart upload. Deliberately does NOT set Content-Type: the browser has
 * to set it itself so it can append the multipart boundary.
 *
 * @param {string} path    e.g. '/admin/teams/import/preview'
 * @param {File}   file    the file input's File object
 * @param {object} fields  extra text fields to send alongside it
 */
export async function apiUpload(path, file, fields = {}, opts = {}) {
  const { kind = 'admin', onUnauthorized } = opts;

  const form = new FormData();
  form.append('file', file, file.name);
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      form.append(key, String(value));
    }
  }

  const headers = {};
  const token = getToken(kind);
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, { method: 'POST', headers, body: form });
  } catch (networkErr) {
    throw new ApiError(0, 'Could not reach the server. Check your connection or the API host in Settings.');
  }

  if (res.status === 401) {
    clearToken(kind);
    if (onUnauthorized) onUnauthorized();
    throw new ApiError(401, 'Session expired. Please log in again.');
  }

  const text = await res.text();
  let data = null;
  if (text) { try { data = JSON.parse(text); } catch { data = null; } }
  if (!res.ok) throw new ApiError(res.status, (data && data.detail) || res.statusText);
  return data;
}

/**
 * Fetches a binary response and hands it to the browser as a download.
 *
 * A plain <a href> can't carry the Authorization header these endpoints
 * require, so the file is fetched as a blob and saved through a temporary
 * object URL instead. The server name is preferred over `fallbackName` — it
 * carries the timestamp — which is why the endpoints expose
 * Content-Disposition via Access-Control-Expose-Headers.
 */
export async function apiDownload(path, { method = 'GET', body, kind = 'admin', fallbackName = 'download.xlsx' } = {}) {
  const headers = {};
  const token = getToken(kind);
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let res;
  try {
    res = await fetch(`${getApiBase()}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new ApiError(0, 'Could not reach the server. Check your connection or the API host in Settings.');
  }

  if (res.status === 401) {
    clearToken(kind);
    throw new ApiError(401, 'Session expired. Please log in again.');
  }
  if (!res.ok) {
    // An error response is JSON, not a spreadsheet.
    let detail = res.statusText;
    try {
      const data = JSON.parse(await res.text());
      if (data && data.detail) detail = data.detail;
    } catch (_) { }
    throw new ApiError(res.status, detail);
  }

  let filename = fallbackName;
  const disposition = res.headers.get('content-disposition');
  if (disposition) {
    const match = /filename="?([^";]+)"?/i.exec(disposition);
    if (match) filename = match[1];
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Revoking immediately can cancel the download in Safari; one tick is enough.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}

export const api = {
  getServerNow,
  getServerTimeOffset,
  team: {
    login: (team_code, password) =>
      apiFetch('/auth/team/login', { method: 'POST', body: { team_code, password }, auth: false }),
    me: () => apiFetch('/teams/me', { kind: 'team' }),
    getActiveRound: () => apiFetch('/rounds/active', { kind: 'team', auth: false }),
    availability: (roundId, suitCode) =>
      apiFetch(`/rounds/${roundId}/selection/availability?suit_code=${encodeURIComponent(suitCode)}`, { kind: 'team' }),
    select: (roundId, suit_code, selected_number) =>
      apiFetch(`/rounds/${roundId}/selection`, { method: 'POST', kind: 'team', body: { suit_code, selected_number } }),
    mySelection: (roundId) =>
      apiFetch(`/rounds/${roundId}/selection/me`, { kind: 'team' }),
    roomSessions: (roomId) =>
      apiFetch(`/rooms/${roomId}/sessions`, { kind: 'team' }),
    roomLeaderboard: (roomId) =>
      apiFetch(`/rooms/${roomId}/leaderboard`, { kind: 'team' }),
    overallLeaderboard: () =>
      apiFetch('/leaderboard/overall', { kind: 'team' }),
    gameLeaderboard: (gameCode) =>
      apiFetch(`/leaderboard/games/${gameCode}`, { kind: 'team' }),

    mindmazeSubmit: (roundId, body) =>
      apiFetch(`/mindmaze/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body }),
    mindmazeLeaderboard: (roomId) =>
      apiFetch(`/mindmaze/rooms/${roomId}/leaderboard`, { kind: 'team' }),
    aceSpadeSubmit: (roundId, body) =>
      apiFetch(`/ace-spade/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body }),
    aceSpadeLeaderboard: (roomId) =>
      apiFetch(`/ace-spade/rooms/${roomId}/leaderboard`, { kind: 'team' }),
    kingDiamondSubmit: (roundId, submitted_number) =>
      apiFetch(`/king-diamond/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body: { submitted_number } }),
    kingDiamondResult: (roundId) =>
      apiFetch(`/king-diamond/rounds/${roundId}/result`, { kind: 'team' }),
    kingDiamondLeaderboard: (roomId) =>
      apiFetch(`/king-diamond/rooms/${roomId}/leaderboard`, { kind: 'team' }),
    jackHeartSymbols: () =>
      apiFetch('/jack-heart/symbols', { kind: 'team' }),
    jackHeartMySuit: (roundId) =>
      apiFetch(`/jack-heart/rounds/${roundId}/my-suit`, { kind: 'team' }),
    jackHeartVisibleSymbols: (roundId) =>
      apiFetch(`/jack-heart/rounds/${roundId}/visible-symbols`, { kind: 'team' }),
    jackHeartSubmit: (roundId, submitted_symbol_id) =>
      apiFetch(`/jack-heart/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body: { submitted_symbol_id } }),
    jackHeartLeaderboard: (roomId) =>
      apiFetch(`/jack-heart/rooms/${roomId}/leaderboard`, { kind: 'team' }),
    viewAck: (sessionId, view_type, round_id = null) =>
      apiFetch(`/sessions/${sessionId}/view-ack`, { method: 'POST', kind: 'team', body: { view_type, round_id } }),
    // Called only after the device has actually rendered its outcome, with the
    // broadcast id it rendered and what it showed, so the admin delivery board
    // can verify each team saw the right result for the current send.
    ackPublishedResults: (payload = null) =>
      apiFetch('/teams/view-published-results', { method: 'POST', kind: 'team', body: payload || undefined }),
    heartbeat: () =>
      apiFetch('/teams/heartbeat', { method: 'POST', kind: 'team' }),
    // Death Card tiebreaker (only while this team is held for one).
    tiebreakState: () => apiFetch('/tiebreak/me', { kind: 'team' }),
    tiebreakPick: (card_index) =>
      apiFetch('/tiebreak/me/pick', { method: 'POST', kind: 'team', body: { card_index } }),
  },

  // Demo (practice) rounds. Deliberately mirrors the shape of api.team's
  // three game surfaces above, method-for-method, so a game screen can pick
  // one or the other at mount time (see gameApi() in the team app's game
  // screens) instead of branching at every call site. Nothing submitted
  // here is ever written to the database — see app/services/demo_service.py.
  demo: {
    roomSessions: (roomId) =>
      apiFetch(`/rooms/${roomId}/demo-sessions`, { kind: 'team' }),

    mindmazeSubmit: (roundId, body) =>
      apiFetch(`/demo/mindmaze/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body }),
    mindmazeLeaderboard: (roomId) =>
      apiFetch(`/demo/rooms/${roomId}/MINDMAZE/leaderboard`, { kind: 'team' }),

    aceSpadeSubmit: (roundId, body) =>
      apiFetch(`/demo/ace-spade/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body }),
    aceSpadeLeaderboard: (roomId) =>
      apiFetch(`/demo/rooms/${roomId}/ACE_SPADE/leaderboard`, { kind: 'team' }),

    kingDiamondSubmit: (roundId, submitted_number) =>
      apiFetch(`/demo/king-diamond/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body: { submitted_number } }),
    kingDiamondResult: (roundId) =>
      apiFetch(`/demo/king-diamond/rounds/${roundId}/result`, { kind: 'team' }),
    kingDiamondLeaderboard: (roomId) =>
      apiFetch(`/demo/rooms/${roomId}/KING_DIAMOND/leaderboard`, { kind: 'team' }),

    jackHeartSubmit: (roundId, submitted_symbol_id) =>
      apiFetch(`/demo/jack-heart/rounds/${roundId}/submit`, { method: 'POST', kind: 'team', body: { submitted_symbol_id } }),
    jackHeartVisibleSymbols: (roundId) =>
      apiFetch(`/demo/jack-heart/rounds/${roundId}/visible-symbols`, { kind: 'team' }),
    jackHeartMySuit: (roundId) =>
      apiFetch(`/demo/jack-heart/rounds/${roundId}/my-suit`, { kind: 'team' }),
    jackHeartLeaderboard: (roomId) =>
      apiFetch(`/demo/rooms/${roomId}/JACK_HEART/leaderboard`, { kind: 'team' }),

    gameLeaderboard: (roomId, gameCode) =>
      apiFetch(`/demo/rooms/${roomId}/${gameCode}/leaderboard`, { kind: 'team' }),
  },

  admin: {
    login: (username, password) =>
      apiFetch('/auth/admin/login', { method: 'POST', body: { username, password }, auth: false }),

    listRounds: () => apiFetch('/admin/rounds', { kind: 'admin' }),
    createRound: (round_number, name) =>
      apiFetch('/admin/rounds', { method: 'POST', kind: 'admin', body: { round_number, name } }),
    autoCreateRound: (name = 'Round 1', teams_per_room = 4) =>
      apiFetch('/admin/rounds/auto', { method: 'POST', kind: 'admin', body: { name, teams_per_room } }),
    getRound: (roundId) => apiFetch(`/admin/rounds/${roundId}`, { kind: 'admin' }),
    setRoundStatus: (roundId, status) =>
      apiFetch(`/admin/rounds/${roundId}/status`, { method: 'PATCH', kind: 'admin', body: { status } }),
    deleteRound: (roundId) =>
      apiFetch(`/admin/rounds/${roundId}`, { method: 'DELETE', kind: 'admin' }),

    listRooms: (roundId) => apiFetch(`/admin/rooms?round_id=${roundId}`, { kind: 'admin' }),
    getRoom: (roomId) => apiFetch(`/admin/rooms/${roomId}`, { kind: 'admin' }),
    setRoomStatus: (roomId, status) =>
      apiFetch(`/admin/rooms/${roomId}/status`, { method: 'PATCH', kind: 'admin', body: { status } }),
    roomAvailability: (roundId, roomId) =>
      apiFetch(`/admin/rounds/${roundId}/rooms/${roomId}/availability`, { kind: 'admin' }),

    moveTeamRoom: (roundId, teamId, target_number) =>
      apiFetch(`/admin/rounds/${roundId}/teams/${teamId}/room`, { method: 'PATCH', kind: 'admin', body: { target_number } }),
    unassignTeam: (roundId, teamId) =>
      apiFetch(`/admin/rounds/${roundId}/teams/${teamId}/selection`, { method: 'DELETE', kind: 'admin' }),

    gameLineup: (roundId) => apiFetch(`/admin/rounds/${roundId}/games`, { kind: 'admin' }),
    setGameLineup: (roundId, entries) =>
      apiFetch(`/admin/rounds/${roundId}/games`, { method: 'PUT', kind: 'admin', body: entries }),
    removeGameFromLineup: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/games/${gameCode}`, { method: 'DELETE', kind: 'admin' }),

    startSession: (roomId, gameCode, duration_minutes, rounds) =>
      apiFetch(`/admin/rooms/${roomId}/sessions/${gameCode}/start`, { method: 'POST', kind: 'admin', body: { duration_minutes, rounds } }),
    roomSessions: (roomId) => apiFetch(`/admin/rooms/${roomId}/sessions`, { kind: 'admin' }),
    pauseSession: (sessionId) => apiFetch(`/admin/sessions/${sessionId}/pause`, { method: 'POST', kind: 'admin' }),
    resumeSession: (sessionId) => apiFetch(`/admin/sessions/${sessionId}/resume`, { method: 'POST', kind: 'admin' }),
    restartSession: (sessionId) => apiFetch(`/admin/sessions/${sessionId}/restart`, { method: 'POST', kind: 'admin' }),
    forceCompleteSession: (sessionId) => apiFetch(`/admin/sessions/${sessionId}/force-complete`, { method: 'POST', kind: 'admin' }),
    showInstructions: (sessionId) => apiFetch(`/admin/sessions/${sessionId}/show-instructions`, { method: 'POST', kind: 'admin' }),
    setRoundDeadline: (sessionId, roundNumber, new_deadline) =>
      apiFetch(`/admin/sessions/${sessionId}/rounds/${roundNumber}/deadline`, { method: 'PATCH', kind: 'admin', body: { new_deadline } }),

    startSessionForRound: (roundId, gameCode, duration_minutes, rounds) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/start`, { method: 'POST', kind: 'admin', body: { duration_minutes, rounds } }),
    startNextSubroundForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/start-next-subround`, { method: 'POST', kind: 'admin' }),
    startSubroundForRound: (roundId, gameCode, subroundNumber) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/subrounds/${subroundNumber}/start`, { method: 'POST', kind: 'admin' }),
    restartSubroundForRound: (roundId, gameCode, subroundNumber) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/subrounds/${subroundNumber}/restart`, { method: 'POST', kind: 'admin' }),
    pauseSubroundForRound: (roundId, gameCode, subroundNumber) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/subrounds/${subroundNumber}/pause`, { method: 'POST', kind: 'admin' }),
    pauseSessionsForRound: (roundId, gameCode) =>


      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/pause`, { method: 'POST', kind: 'admin' }),
    resumeSessionsForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/resume`, { method: 'POST', kind: 'admin' }),
    restartSessionsForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/restart`, { method: 'POST', kind: 'admin' }),
    forceCompleteSessionsForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/force-complete`, { method: 'POST', kind: 'admin' }),
    showInstructionsForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/show-instructions`, { method: 'POST', kind: 'admin' }),
    publishGameForRound: (roundId, gameCode) =>
      apiFetch(`/admin/rounds/${roundId}/sessions/${gameCode}/publish-results`, { method: 'POST', kind: 'admin' }),
    getRoundGameSessions: (roundId) =>
      apiFetch(`/admin/rounds/${roundId}/game-sessions`, { kind: 'admin' }),

    // Demo (practice) round control — same vocabulary as the real
    // round-wide session controls above. `restart` is the practice-again
    // control: it re-deals a fresh attempt from any state.
    demo: {
      list: (roundId) => apiFetch(`/admin/rounds/${roundId}/demo`, { kind: 'admin' }),
      start: (roundId, gameCode, duration_minutes, rounds) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/start`, { method: 'POST', kind: 'admin', body: { duration_minutes, rounds } }),
      restart: (roundId, gameCode, body = {}) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/restart`, { method: 'POST', kind: 'admin', body }),
      end: (roundId, gameCode) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/end`, { method: 'POST', kind: 'admin' }),
      pause: (roundId, gameCode) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/pause`, { method: 'POST', kind: 'admin' }),
      resume: (roundId, gameCode) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/resume`, { method: 'POST', kind: 'admin' }),
      startSubround: (roundId, gameCode, subroundNumber) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/subrounds/${subroundNumber}/start`, { method: 'POST', kind: 'admin' }),
      restartSubround: (roundId, gameCode, subroundNumber) =>
        apiFetch(`/admin/rounds/${roundId}/demo/${gameCode}/subrounds/${subroundNumber}/restart`, { method: 'POST', kind: 'admin' }),
    },


    teams: {
      create: (team_code, team_name, password) =>
        apiFetch('/admin/teams', { method: 'POST', kind: 'admin', body: { team_code, team_name, password } }),
      list: (roundId) => apiFetch(`/admin/teams${roundId ? `?round_id=${roundId}` : ''}`, { kind: 'admin' }),
      detail: (teamId, roundId) => apiFetch(`/admin/teams/${teamId}${roundId ? `?round_id=${roundId}` : ''}`, { kind: 'admin' }),
      setPassword: (teamId, new_password) =>
        apiFetch(`/admin/teams/${teamId}/password`, { method: 'PATCH', kind: 'admin', body: { new_password } }),
      remove: (teamId) => apiFetch(`/admin/teams/${teamId}`, { method: 'DELETE', kind: 'admin' }),

      // Bulk registration import. Two calls on purpose: `importPreview`
      // validates and shows what would be created without writing anything,
      // `importCommit` takes the reviewed rows back and creates them in one
      // transaction. See app/api/v1/admin_data.py.
      importTemplate: () =>
        apiDownload('/admin/teams/import/template', { fallbackName: 'team-import-template.xlsx' }),
      importPreview: (file, overrides = {}) =>
        apiUpload('/admin/teams/import/preview', file, {
          team_name_column: overrides.team_name,
          leader_name_column: overrides.leader_name,
          leader_phone_column: overrides.leader_phone,
          leader_email_column: overrides.leader_email,
        }),
      importCommit: (rows) =>
        apiFetch('/admin/teams/import', { method: 'POST', kind: 'admin', body: { rows } }),
      // Passwords only exist in the clear in the import response, so the
      // credentials sheet is built from that payload rather than re-read.
      credentialsExport: (result) =>
        apiDownload('/admin/teams/credentials-export', {
          method: 'POST',
          body: result,
          fallbackName: 'team-logins.xlsx',
        }),
    },

    mindmaze: {
      forceClose: (roundId) => apiFetch(`/admin/mindmaze/rounds/${roundId}/force-close`, { method: 'POST', kind: 'admin' }),
      results: (roundId) => apiFetch(`/admin/mindmaze/rounds/${roundId}/results`, { kind: 'admin' }),
      patchResult: (roundId, teamId, round_score) =>
        apiFetch(`/admin/mindmaze/rounds/${roundId}/results/${teamId}`, { method: 'PATCH', kind: 'admin', body: { round_score } }),
    },
    aceSpade: {
      forceClose: (roundId) => apiFetch(`/admin/ace-spade/rounds/${roundId}/force-close`, { method: 'POST', kind: 'admin' }),
      results: (roundId) => apiFetch(`/admin/ace-spade/rounds/${roundId}/results`, { kind: 'admin' }),
      patchResult: (roundId, teamId, round_score) =>
        apiFetch(`/admin/ace-spade/rounds/${roundId}/results/${teamId}`, { method: 'PATCH', kind: 'admin', body: { round_score } }),
    },
    kingDiamond: {
      forceClose: (roundId) => apiFetch(`/admin/king-diamond/rounds/${roundId}/force-close`, { method: 'POST', kind: 'admin' }),
      submissions: (roundId) => apiFetch(`/admin/king-diamond/rounds/${roundId}/submissions`, { kind: 'admin' }),
      patchSubmission: (roundId, submissionId, patch) =>
        apiFetch(`/admin/king-diamond/rounds/${roundId}/submissions/${submissionId}`, { method: 'PATCH', kind: 'admin', body: patch }),
    },
    jackHeart: {
      forceClose: (roundId) => apiFetch(`/admin/jack-heart/rounds/${roundId}/force-close`, { method: 'POST', kind: 'admin' }),
      answers: (roundId) => apiFetch(`/admin/jack-heart/rounds/${roundId}/answers`, { kind: 'admin' }),
      assignments: (roundId) => apiFetch(`/admin/jack-heart/rounds/${roundId}/assignments`, { kind: 'admin' }),
    },

    scheduler: {
      list: () => apiFetch('/admin/scheduler/jobs', { kind: 'admin' }),
      create: (game_code, round_id, run_at) =>
        apiFetch('/admin/scheduler/jobs', { method: 'POST', kind: 'admin', body: { game_code, round_id, run_at } }),
      remove: (jobId) => apiFetch(`/admin/scheduler/jobs/${jobId}`, { method: 'DELETE', kind: 'admin' }),
    },

    recomputeResults: (roomId) => apiFetch(`/admin/rooms/${roomId}/recompute-results`, { method: 'POST', kind: 'admin' }),
    roomResults: (roomId) => apiFetch(`/admin/rooms/${roomId}/results`, { kind: 'admin' }),
    roomLeaderboard: (roomId) => apiFetch(`/admin/rooms/${roomId}/leaderboard`, { kind: 'admin' }),
    roundLeaderboard: (roundId) => apiFetch(`/admin/rounds/${roundId}/leaderboard`, { kind: 'admin' }),
    setQualificationRule: (roundId, top_n, room_id) =>
      apiFetch(`/admin/rounds/${roundId}/qualification-rule`, { method: 'PUT', kind: 'admin', body: room_id ? { top_n, room_id } : { top_n } }),
    qualificationRules: (roundId) => apiFetch(`/admin/rounds/${roundId}/qualification-rules`, { kind: 'admin' }),
    publishLeaderboard: (roomId) => apiFetch(`/admin/rooms/${roomId}/publish-leaderboard`, { method: 'POST', kind: 'admin' }),
    publishRoundLeaderboard: (roundId) => apiFetch(`/admin/rounds/${roundId}/publish-leaderboard`, { method: 'POST', kind: 'admin' }),
    getTeamConnections: (roundId) => apiFetch(`/admin/rounds/${roundId}/team-connections`, { kind: 'admin' }),
    // Death Card tiebreakers for the round.
    tiebreaks: (roundId) => apiFetch(`/tiebreak/admin/rounds/${roundId}`, { kind: 'admin' }),
    tiebreakStart: (sessionId) => apiFetch(`/tiebreak/admin/sessions/${sessionId}/start`, { method: 'POST', kind: 'admin' }),
    tiebreakAdvance: (sessionId) => apiFetch(`/tiebreak/admin/sessions/${sessionId}/advance`, { method: 'POST', kind: 'admin' }),
    tiebreakReset: (sessionId) => apiFetch(`/tiebreak/admin/sessions/${sessionId}/reset`, { method: 'POST', kind: 'admin' }),

    // Round 2 qualifiers. `winners` is the same data as JSON so the console
    // can show the list before downloading it; both recompute room results
    // first by default, so a late score correction is always reflected.
    winners: (roundId, recompute = true) =>
      apiFetch(`/admin/rounds/${roundId}/winners?recompute=${recompute}`, { kind: 'admin' }),
    exportWinners: (roundId, recompute = true) =>
      apiDownload(`/admin/rounds/${roundId}/winners/export?recompute=${recompute}`, {
        fallbackName: 'round-qualifiers.xlsx',
      }),

    admins: {
      create: (username, password, role) =>
        apiFetch('/admin/admins', { method: 'POST', kind: 'admin', body: { username, password, role } }),
      list: () => apiFetch('/admin/admins', { kind: 'admin' }),
      setPassword: (adminId, new_password) =>
        apiFetch(`/admin/admins/${adminId}/password`, { method: 'PATCH', kind: 'admin', body: { new_password } }),
      remove: (adminId) => apiFetch(`/admin/admins/${adminId}`, { method: 'DELETE', kind: 'admin' }),
    },
  },
};
