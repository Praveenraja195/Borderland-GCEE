import { api } from '../../../shared/js/api.js';
import { LiveChannel } from '../../../shared/js/ws.js';

// Live leaderboard for the whole round. Two views over ONE dataset
// (/admin/rounds/{id}/leaderboard, which carries both room_rank and
// overall_rank per team): "By Room" stacks every room's standings in room
// order; "Overall" ranks every team across rooms. Scores are the ungated live
// values admins are allowed to see before results are published.
//
// Freshness: the room / overall WebSocket channels fire whenever a sub-round
// closes or results are recomputed, and a slow poll catches in-flight
// submissions that don't push (game submit endpoints don't publish).

const SUIT_SYMBOLS = { SPADE: '♠', HEART: '♥', DIAMOND: '♦', CLUB: '♣' };
const POLL_MS = 5000;
const VIEW_KEY = 'bl_admin_lb_view';

export function renderLeaderboardScreen(root, navigate) {
  let view = 'rooms';
  try { view = localStorage.getItem(VIEW_KEY) === 'overall' ? 'overall' : 'rooms'; } catch (_) {}

  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Leaderboard</h1>
      <div class="lb-toolbar">
        <span class="bl-sb-live-indicator"><span class="pulse-dot"></span>LIVE</span>
        <div class="lb-view-toggle" role="tablist">
          <button type="button" class="lb-view-btn" data-view="rooms" role="tab"><span class="mi">meeting_room</span> By Room</button>
          <button type="button" class="lb-view-btn" data-view="overall" role="tab"><span class="mi">emoji_events</span> Overall</button>
        </div>
      </div>
    </div>
    <div id="lb-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#lb-body');
  const viewBtns = [...root.querySelectorAll('.lb-view-btn')];

  let round = null;        // RoundDetailOut (rooms in order)
  let rows = [];           // rows from /admin/rounds/{id}/leaderboard
  let lastTotals = new Map();
  const channels = [];
  let pollTimer = null;
  let refreshTimer = null;
  let refreshing = false;
  let disposed = false;

  function setView(next) {
    view = next;
    try { localStorage.setItem(VIEW_KEY, view); } catch (_) {}
    viewBtns.forEach(b => b.classList.toggle('active', b.dataset.view === view));
    render();
  }
  viewBtns.forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
  viewBtns.forEach(b => b.classList.toggle('active', b.dataset.view === view));

  const fmt = (v) => (v === null || v === undefined) ? '—' : Number(v).toFixed(1);

  function statusPill(r) {
    if (r.is_qualified === true) return '<span class="bl-sb-status-pill qualified">QUALIFIED</span>';
    if (r.is_qualified === false) return '<span class="bl-sb-status-pill eliminated">ELIMINATED</span>';
    return '<span class="bl-sb-status-pill active">ACTIVE</span>';
  }

  function teamCell(r) {
    const suitCode = (r.team_suit_code || 'SPADE').toUpperCase();
    const symbol = r.team_suit_symbol || SUIT_SYMBOLS[suitCode] || '♠';
    return `
      <div class="bl-sb-team-cell">
        <span class="bl-sb-suit-icon ${suitCode.toLowerCase()}" title="${suitCode}">${symbol}</span>
        <div>
          <div class="bl-sb-team-code">${r.team_code}</div>
          ${r.team_name ? `<div class="bl-sb-team-sub">${r.team_name}</div>` : ''}
        </div>
      </div>`;
  }

  // One standings table. `rankKey` picks room_rank or overall_rank; the
  // ROOM column is only shown on the overall view.
  function table(list, rankKey, withRoom) {
    return `
      <div class="bl-sb-table-wrap">
        <table class="bl-sb-table">
          <thead>
            <tr>
              <th class="bl-sb-th center" style="width: 56px;">POS</th>
              <th class="bl-sb-th">TEAM &amp; SUIT</th>
              ${withRoom ? '<th class="bl-sb-th center" style="width: 90px;">ROOM</th>' : ''}
              <th class="bl-sb-th center" title="MindMaze">🧠 MM</th>
              <th class="bl-sb-th center" title="Ace of Spades">♠ AS</th>
              <th class="bl-sb-th center" title="King of Diamonds">♦ KD</th>
              <th class="bl-sb-th center" title="Jack of Hearts">♥ JH</th>
              <th class="bl-sb-th right" style="min-width: 90px;">TOTAL</th>
              <th class="bl-sb-th center" style="min-width: 95px;">STATUS</th>
            </tr>
          </thead>
          <tbody>
            ${list.map(r => {
              const rank = r[rankKey];
              const rankClass = rank === 1 ? 'rank-1' : rank === 2 ? 'rank-2' : rank === 3 ? 'rank-3' : '';
              return `
                <tr class="bl-sb-row" data-team-code="${r.team_code}">
                  <td class="bl-sb-td center"><span class="bl-sb-rank-badge ${rankClass}">#${rank}</span></td>
                  <td class="bl-sb-td">${teamCell(r)}</td>
                  ${withRoom ? `<td class="bl-sb-td center"><a class="lb-room-link" href="#/rooms/${r.room_id}/${round?.round_id || ''}">${r.room_code}</a></td>` : ''}
                  <td class="bl-sb-td center"><span class="bl-sb-score-pill active-score">${fmt(r.mindmaze_score)}</span></td>
                  <td class="bl-sb-td center"><span class="bl-sb-score-pill active-score">${fmt(r.ace_spade_score)}</span></td>
                  <td class="bl-sb-td center"><span class="bl-sb-score-pill active-score">${fmt(r.king_diamond_score)}</span></td>
                  <td class="bl-sb-td center"><span class="bl-sb-score-pill active-score">${fmt(r.jack_heart_score)}</span></td>
                  <td class="bl-sb-td right"><div class="bl-sb-total-box">${fmt(r.total_score)}<span class="bl-sb-total-pts">PTS</span></div></td>
                  <td class="bl-sb-td center">${statusPill(r)}</td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;
  }

  function renderByRoom() {
    const rooms = [...(round?.rooms || [])].sort((a, b) => (a.room_number || 0) - (b.room_number || 0));
    if (!rooms.length) {
      return `<div class="empty-state"><div class="empty-icon"><span class="mi">meeting_room</span></div>No rooms in this round yet.</div>`;
    }
    return `<div class="lb-rooms">${rooms.map(room => {
      const list = rows
        .filter(r => r.room_id === room.room_id)
        .sort((a, b) => a.room_rank - b.room_rank || a.team_code.localeCompare(b.team_code));
      return `
        <section class="bl-admin-scoreboard lb-room-card" id="lb-room-${room.room_id}">
          <div class="bl-sb-header">
            <div class="bl-sb-header-left">
              <div>
                <div class="bl-sb-title">ROOM ${room.room_number} · ${room.room_code}</div>
                <div class="bl-sb-subtitle">${list.length} team${list.length === 1 ? '' : 's'}</div>
              </div>
            </div>
            <div class="bl-sb-header-actions">
              <a class="bl-sb-btn" href="#/rooms/${room.room_id}/${round.round_id}"><span class="mi">tune</span> Room control</a>
            </div>
          </div>
          ${list.length
            ? table(list, 'room_rank', false)
            : '<div class="lb-room-empty">No teams seated in this room yet.</div>'}
        </section>`;
    }).join('')}</div>`;
  }

  function renderOverall() {
    const list = [...rows].sort((a, b) => a.overall_rank - b.overall_rank || a.team_code.localeCompare(b.team_code));
    if (!list.length) {
      return `<div class="empty-state"><div class="empty-icon"><span class="mi">leaderboard</span></div>No teams seated yet. Standings appear once teams pick a room.</div>`;
    }
    const roomCount = new Set(list.map(r => r.room_id)).size;
    return `
      <section class="bl-admin-scoreboard">
        <div class="bl-sb-header">
          <div class="bl-sb-header-left">
            <div>
              <div class="bl-sb-title">OVERALL STANDINGS</div>
              <div class="bl-sb-subtitle">${list.length} teams across ${roomCount} room${roomCount === 1 ? '' : 's'} · ranked by total points</div>
            </div>
          </div>
        </div>
        ${table(list, 'overall_rank', true)}
      </section>`;
  }

  function render() {
    if (disposed) return;
    if (!round) return;
    body.innerHTML = view === 'overall' ? renderOverall() : renderByRoom();

    // Flash rows whose total changed since the previous render so a live
    // update is visible at a glance.
    const next = new Map(rows.map(r => [r.team_code, r.total_score]));
    if (lastTotals.size) {
      body.querySelectorAll('.bl-sb-row').forEach(tr => {
        const code = tr.dataset.teamCode;
        if (lastTotals.has(code) && lastTotals.get(code) !== next.get(code)) {
          tr.classList.add('lb-row-flash');
          setTimeout(() => tr.classList.remove('lb-row-flash'), 1500);
        }
      });
    }
    lastTotals = next;
  }

  async function refresh() {
    if (refreshing || disposed) return;
    refreshing = true;
    try {
      const fresh = await api.admin.roundLeaderboard(round.round_id);
      if (Array.isArray(fresh)) {
        rows = fresh;
        render();
      }
    } catch (_) {
      // keep showing the last good standings
    } finally {
      refreshing = false;
    }
  }

  // Several channels fire for one recompute; collapse them into one fetch.
  function scheduleRefresh() {
    if (refreshTimer) return;
    refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 250);
  }

  async function init() {
    try {
      const rounds = await api.admin.listRounds();
      if (!rounds.length) {
        body.innerHTML = `<div class="empty-state"><div class="empty-icon"><span class="mi">leaderboard</span></div>No round yet — create the round from the Dashboard first.</div>`;
        return;
      }
      round = await api.admin.getRound(rounds[0].round_id);
      rows = await api.admin.roundLeaderboard(round.round_id);
      render();
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
      return;
    }
    if (disposed) return;

    channels.push(new LiveChannel('/leaderboard/overall', scheduleRefresh, 'admin'));
    (round.rooms || []).forEach(room => {
      channels.push(new LiveChannel(`/rooms/${room.room_id}/leaderboard`, scheduleRefresh, 'admin'));
    });
    pollTimer = setInterval(refresh, POLL_MS);
  }

  init();

  return () => {
    disposed = true;
    if (pollTimer) clearInterval(pollTimer);
    if (refreshTimer) clearTimeout(refreshTimer);
    channels.forEach(ch => { try { ch.close(); } catch (_) {} });
  };
}
