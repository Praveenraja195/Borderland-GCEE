import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';

export function renderRoomsScreen(root, navigate, role) {
  let pollInterval = null;

  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Rooms</h1>
    </div>
    <div id="rooms-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#rooms-body');

  async function load(silent = false) {
    if (!silent) {
      body.innerHTML = `<div class="spinner"></div>`;
    }
    const topline = root.querySelector('.admin-topline');

    try {
      const rounds = await api.admin.listRounds();
      if (!rounds.length) {
        if (!silent) {
          topline.innerHTML = `<h1 class="admin-h1">Rooms</h1>`;
          renderNoRound();
        }
        return;
      }

      const roundSummary = rounds[0];
      const detail = await api.admin.getRound(roundSummary.round_id);

      if (!silent) {
        topline.innerHTML = `
          <div style="display:flex;align-items:center;gap:12px;">
            <h1 class="admin-h1">Rooms</h1>
            <span class="pill ${detail.status}" style="font-size:0.7rem;">${detail.name} — ${detail.status?.replace('_', ' ')}</span>
          </div>
        `;
        renderRoomsContent(detail);
      } else {
        const roomGridEl = body.querySelector('#room-grid');
        if (roomGridEl) renderRoomGrid(roomGridEl, detail);
      }
    } catch (err) {
      if (!silent) {
        body.innerHTML = `<p class="status-note error">${err.message}</p>`;
      }
    }
  }

  function renderNoRound() {
    body.innerHTML = `
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">Teams Registered</div>
          <div class="stat-value" id="team-count-stat">...</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Status</div>
          <div class="stat-value" style="font-size:1rem;font-family:var(--font-body-en);">No round created</div>
        </div>
      </div>

      <div class="setup-panel" id="setup-panel">
        <h3><span class="mi">construction</span> Create Rooms</h3>
        <p>Register teams first in the Teams tab, then create rooms here.<br>
           Rooms are calculated automatically based on team count.</p>
        <div class="setup-config">
          <label>Teams per room:</label>
          <input type="number" id="teams-per-room" value="4" min="1" max="10" />
          <label>Round name:</label>
          <input type="text" id="round-name" value="Round 1" style="width:120px;text-align:left;" />
        </div>
        <button class="btn primary" id="auto-create-btn"><span class="mi">add_circle</span> Create Round & Rooms</button>
      </div>
    `;

    api.admin.teams.list().then(teams => {
      const el = body.querySelector('#team-count-stat');
      if (el) el.textContent = teams.length;
    }).catch(() => {});

    body.querySelector('#auto-create-btn').addEventListener('click', async () => {
      const teamsPerRoom = Number(body.querySelector('#teams-per-room').value) || 4;
      const roundName = body.querySelector('#round-name').value.trim() || 'Round 1';
      const btn = body.querySelector('#auto-create-btn');
      btn.disabled = true;
      btn.innerHTML = '<span class="mi">hourglass_empty</span> Creating...';
      try {
        const result = await api.admin.autoCreateRound(roundName, teamsPerRoom);
        toast(`Round created with ${result.rooms.length} rooms!`);
        load();
      } catch (err) {
        toast(err.message, { error: true });
        btn.disabled = false;
        btn.innerHTML = '<span class="mi">add_circle</span> Create Round & Rooms';
      }
    });
  }

  function renderRoomsContent(detail) {
    const rooms = detail.rooms || [];
    const totalTeams = rooms.reduce((sum, r) => sum + (r.team_count || 0), 0);

    body.innerHTML = `
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-label">Total Rooms</div>
          <div class="stat-value">${rooms.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Assigned Teams</div>
          <div class="stat-value">${totalTeams}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Round Status</div>
          <div class="stat-value" style="font-size:1rem;font-family:var(--font-body-en);">
            <span class="pill ${detail.status}">${detail.status?.replace('_', ' ')}</span>
          </div>
        </div>
      </div>

      <div class="section-header">
        <span class="section-icon"><span class="mi">meeting_room</span></span> All Rooms (${rooms.length})
      </div>
      <div class="room-grid" id="room-grid"></div>
    `;

    renderRoomGrid(body.querySelector('#room-grid'), detail);
  }

  function renderRoomGrid(el, detail) {
    const rooms = detail.rooms || [];
    if (!rooms.length) {
      el.innerHTML = `<div class="empty-state"><div class="empty-icon"><span class="mi mi-xl">meeting_room</span></div>No rooms found.</div>`;
      return;
    }
    el.innerHTML = rooms.map(r => `
      <div class="room-card" data-room="${r.room_id}" data-round="${detail.round_id}">
        <div class="room-code">${r.room_code || 'R' + String(r.room_number).padStart(2, '0')}</div>
        <div class="room-meta">
          <span class="room-teams-count"><span class="mi">group</span> ${r.team_count ?? 0} teams</span>
          <span class="pill ${r.status || 'NOT_STARTED'}">${(r.status || 'NOT_STARTED').replace('_', ' ')}</span>
        </div>
      </div>
    `).join('');

    el.querySelectorAll('.room-card').forEach(card => {
      card.addEventListener('click', () => {
        navigate(`#/rooms/${card.dataset.room}/${card.dataset.round}`);
      });
    });
  }

  load();
  pollInterval = setInterval(() => {
    if (!root.isConnected) {
      clearInterval(pollInterval);
      return;
    }
    if (document.querySelector('.modal-backdrop')) return;
    load(true);
  }, 2500);

  return () => {
    if (pollInterval) clearInterval(pollInterval);
  };
}
