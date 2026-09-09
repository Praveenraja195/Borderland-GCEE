import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';
import { LiveChannel } from '../../../shared/js/ws.js';
import { GAMES } from '../../../shared/js/copy.js';

export function renderRoomControl(root, navigate, roomId, roundId) {
  root.innerHTML = `
    <p class="admin-crumb"><a href="#/rooms">← Rooms</a></p>
    <div class="admin-topline">
      <h1 class="admin-h1" id="room-header">Room <span class="mono">${roomId.slice(0, 8)}</span></h1>
    </div>

    <div class="section-header"><span class="section-icon"><span class="mi">group</span></span> Team Management</div>
    <div class="dash-card" id="teams-area" style="margin-bottom:24px;"><div class="spinner"></div></div>

    <div class="section-header"><span class="section-icon"><span class="mi">sports_esports</span></span> Active Game Sessions</div>
    <div id="demo-notice"></div>
    <div class="dash-card" id="sessions-area" style="margin-bottom:24px;"><div class="spinner"></div></div>

    <div class="section-header"><span class="section-icon"><span class="mi">leaderboard</span></span> Scoreboard</div>
    <div class="dash-card" id="lb-area"><div class="spinner"></div></div>
  `;

  const teamsArea = root.querySelector('#teams-area');
  const sessionsArea = root.querySelector('#sessions-area');
  const demoNotice = root.querySelector('#demo-notice');
  const lbArea = root.querySelector('#lb-area');
  let roomData = null;
  let channel = null;
  let sessionsChannel = null;
  let lastAssignedTeamsCount = 0;

  async function loadRoomDetails() {
    try {
      roomData = await api.admin.getRoom(roomId);
      if (roomData) {
        root.querySelector('#room-header').innerHTML = `Room <span class="mono">${roomData.room_code || roomData.room_number}</span> <span class="pill ${roomData.status || 'NOT_STARTED'}" style="margin-left:8px;font-size:0.6rem;">${(roomData.status || '').replace('_', ' ')}</span>`;
      }
    } catch (_) {}
  }

  async function loadTeams() {
    teamsArea.innerHTML = `<div class="spinner"></div>`;
    try {
      const allTeams = await api.admin.teams.list(roundId);
      const roomCode = roomData?.room_code || `R${String(roomData?.room_number || '').padStart(2, '0')}`;
      const assigned = allTeams.filter(t => t.room_code === roomCode);
      const unassigned = allTeams.filter(t => !t.room_code && !t.has_selected);
      lastAssignedTeamsCount = assigned.length;
      renderTeams(assigned, unassigned, allTeams);
      loadSessions(assigned.length);
    } catch (err) {
      teamsArea.innerHTML = `<p class="status-note error">${err.message}</p>`;
      loadSessions(0); // still try to show sessions even if team list fails
    }
  }

  function renderTeams(assigned, unassigned, allTeams) {
    // Find teams assigned to other rooms (for potential reassignment)
    const otherRooms = allTeams.filter(t => t.room_code && t.room_code !== (roomData?.room_code || ''));

    teamsArea.innerHTML = `
      <h3 style="margin-bottom:12px;">Assigned Teams (${assigned.length})</h3>
      ${assigned.length === 0 ? '<p class="empty-state">No teams assigned to this room yet.</p>' : `
        <table class="dtable">
          <thead><tr><th>Code</th><th>Name</th><th>Suit</th><th>Actions</th></tr></thead>
          <tbody>
            ${assigned.map(t => `
              <tr>
                <td class="mono"><strong>${t.team_code}</strong></td>
                <td>${t.team_name}</td>
                <td>${t.suit_code || '—'}</td>
                <td>
                  <div class="btn-row">
                    <button class="btn" data-move="${t.team_id}" data-code="${t.team_code}"><span class="mi">swap_horiz</span> Move</button>
                    <button class="btn danger" data-unassign="${t.team_id}" data-code="${t.team_code}"><span class="mi">person_remove</span> Remove</button>
                  </div>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `}

      ${unassigned.length ? `
        <div style="margin-top:16px;padding:16px;border:1px dashed rgba(0,0,0,0.12);border-radius:10px;background:#fafbfc;">
          <h3 style="margin-bottom:8px;font-size:0.85rem;display:flex;align-items:center;gap:6px;"><span class="mi">person_add</span> Add Unassigned Team</h3>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <select id="unassigned-select" class="move-select">
              ${unassigned.map(t => `<option value="${t.team_id}">${t.team_code} — ${t.team_name}</option>`).join('')}
            </select>
            <button id="assign-here-btn" class="btn primary">Add to Room ${roomData?.room_number || ''}</button>
          </div>
        </div>
      ` : ''}
    `;

    // Wire move buttons
    teamsArea.querySelectorAll('[data-move]').forEach(btn => {
      btn.addEventListener('click', () => openMoveModal(btn.dataset.move, btn.dataset.code));
    });

    // Wire unassign buttons
    teamsArea.querySelectorAll('[data-unassign]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (!confirm(`Remove team ${btn.dataset.code} from this room?`)) return;
        try {
          await api.admin.unassignTeam(roundId, btn.dataset.unassign);
          toast(`Removed team ${btn.dataset.code}`);
          loadTeams();
        } catch (err) { toast(err.message, { error: true }); }
      });
    });

    // Wire assign button
    const assignBtn = teamsArea.querySelector('#assign-here-btn');
    if (assignBtn) {
      assignBtn.addEventListener('click', async () => {
        const teamId = teamsArea.querySelector('#unassigned-select').value;
        const targetRoomNumber = roomData?.room_number;
        if (!teamId || !targetRoomNumber) return;
        try {
          await api.admin.moveTeamRoom(roundId, teamId, targetRoomNumber);
          toast('Team added to room');
          loadTeams();
        } catch (err) { toast(err.message, { error: true }); }
      });
    }
  }

  /** While a demo is running, this room's teams are on the practice screen
   *  for that game and the real session below is untouched — which looks
   *  alarming from here without an explanation. Demos are round-wide and
   *  are driven from the Dashboard, so this is read-only on purpose. */
  async function loadDemoNotice() {
    if (!demoNotice || !roundId) return;
    let demos = [];
    try {
      demos = await api.admin.demo.list(roundId);
    } catch (_) {
      demos = [];
    }

    const mine = (demos || []).filter(d => d.room_id === roomId);
    if (!mine.length) {
      demoNotice.innerHTML = '';
      return;
    }

    demoNotice.innerHTML = mine.map(d => {
      const open = (d.rounds || []).find(r => r.start_time && !r.is_closed);
      const label = d.status === 'PAUSED'
        ? 'paused'
        : d.status === 'COMPLETED'
          ? 'finished'
          : open
            ? `on sub-round ${open.round_number}`
            : 'between sub-rounds';
      const submitted = open && open.submitted_teams ? open.submitted_teams.length : 0;
      return `
        <div class="demo-panel live" style="margin-bottom:12px;">
          <div class="demo-panel-head">
            <span class="demo-tag">DEMO</span>
            <span class="demo-title">${GAMES[d.game_code]?.en || d.game_code} practice round is live</span>
            <span class="demo-status ${d.status === 'PAUSED' ? 'paused' : d.status === 'COMPLETED' ? 'done' : 'running'}">${label}</span>
            ${d.attempt > 1 ? `<span class="demo-attempt">Attempt ${d.attempt}</span>` : ''}
            ${open ? `<span class="demo-scope">${submitted} / ${d.total_room_teams} submitted</span>` : ''}
          </div>
          <p class="demo-note">
            This room's teams are on the practice screen for this game. Nothing they score is saved,
            and the real session below is untouched. Control demos from the <strong>Dashboard</strong>.
          </p>
        </div>
      `;
    }).join('');
  }

  async function loadSessions(assignedTeamsCount) {
    if (assignedTeamsCount !== undefined) {
      lastAssignedTeamsCount = assignedTeamsCount;
    }
    const teamCount = lastAssignedTeamsCount;
    try {
      const sessions = await api.admin.roomSessions(roomId);
      if (!sessions || !sessions.length) {
        sessionsArea.innerHTML = `<div class="empty-state">No game sessions active in this room. Start games from the Dashboard.</div>`;
        return;
      }
      
      sessionsArea.innerHTML = sessions.map(s => {
        const gameName = GAMES[s.game_code]?.en || s.game_code;
        const rounds = s.rounds || [];
        const startedRounds = rounds.filter(r => r.start_time);
        const allRoundsClosed = rounds.length > 0 && rounds.every(r => r.is_closed);
        const allStartedClosed = startedRounds.length > 0 && startedRounds.every(r => r.is_closed);
        const isDbCompleted = s.session.status === 'COMPLETED';

        let sessionPillHtml = '';
        if (isDbCompleted || allRoundsClosed) {
          sessionPillHtml = `<span class="pill COMPLETED">COMPLETED</span>`;
        } else if (s.session.status === 'PAUSED') {
          sessionPillHtml = `<span class="pill" style="background:#fef3c7;color:#b45309;">PAUSED</span>`;
        } else if (allStartedClosed && startedRounds.length < rounds.length) {
          sessionPillHtml = `<span class="pill COMPLETED" style="background:#e0f2fe;color:#0369a1;">ROUND ${startedRounds.length} CLOSED</span>`;
        } else if (s.session.status === 'IN_PROGRESS') {
          sessionPillHtml = `<span class="pill ACTIVE">IN PROGRESS</span>`;
        } else {
          sessionPillHtml = `<span class="pill" style="opacity:0.6;">${(s.session.status || 'NOT STARTED').replace('_', ' ')}</span>`;
        }

        const canForceComplete = s.session.status === 'IN_PROGRESS' && !isDbCompleted;

        return `
          <div class="session-block" style="margin-bottom: 20px; padding: 12px; border: 1px solid var(--bl-border); border-radius: 8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
              <h4 style="margin:0; display:flex; align-items:center; gap:8px;">
                ${gameName}
                ${sessionPillHtml}
              </h4>
              <div class="btn-row" style="margin:0;">
                ${canForceComplete ? `
                  <button class="btn danger" style="padding:3px 8px; font-size:0.75rem;" data-force-complete="${s.session.session_id}">
                    <span class="mi">done_all</span> Mark Completed
                  </button>
                ` : ''}
              </div>
            </div>
            <table class="dtable" style="font-size:0.8rem;">
              <thead>
                <tr>
                  <th>Round</th>
                  <th>Deadline</th>
                  <th>Status</th>
                  <th>Submissions</th>
                </tr>
              </thead>
              <tbody>
                ${rounds.map(r => {
                  const isClosed = r.is_closed;
                  const count = r.submitted_teams ? r.submitted_teams.length : 0;
                  const allDone = teamCount > 0 && count >= teamCount;
                  const submissionStatus = allDone
                    ? `<span style="color:#1a7a3c; font-weight:700;">${count}/${teamCount} (All submitted)</span>`
                    : `<span>${count}/${teamCount}</span>`;
                  
                  let roundStatusHtml = '';
                  if (isClosed) {
                    roundStatusHtml = '<span class="pill COMPLETED">Closed</span>';
                  } else if (r.start_time) {
                    roundStatusHtml = '<span class="pill ACTIVE">In Progress</span>';
                  } else {
                    roundStatusHtml = '<span class="pill" style="opacity:0.5;">Not Started</span>';
                  }

                  return `
                    <tr>
                      <td>Round ${r.round_number}</td>
                      <td>${r.deadline ? new Date(r.deadline).toLocaleTimeString() : '—'}</td>
                      <td>${roundStatusHtml}</td>
                      <td>
                        ${submissionStatus}
                        ${r.submitted_teams && r.submitted_teams.length > 0 ? `<div style="font-size:0.7rem; color:var(--bl-gray); margin-top:2px;">${r.submitted_teams.join(', ')}</div>` : ''}
                      </td>
                    </tr>
                  `;
                }).join('')}
              </tbody>
            </table>
          </div>
        `;
      }).join('');

      // Wire force complete buttons
      sessionsArea.querySelectorAll('[data-force-complete]').forEach(btn => {
        btn.addEventListener('click', async () => {
          if (!confirm('Mark this game session as COMPLETED?')) return;
          try {
            await api.admin.forceCompleteSession(btn.dataset.forceComplete);
            toast('Session marked completed');
            loadSessions();
            loadLeaderboard();
          } catch (err) {
            toast(err.message, { error: true });
          }
        });
      });
    } catch (err) {
      sessionsArea.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  function openMoveModal(teamId, teamCode) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3>Move Team ${teamCode}</h3>
        <p style="font-size:0.82rem;color:#64748b;margin-bottom:16px;">
          Enter the target room number to move this team to.
        </p>
        <div class="field">
          <label class="tier-label"><span class="primary">Target Room Number</span></label>
          <input id="target-room-num" type="number" min="1" value="1" />
        </div>
        <div class="btn-row">
          <button class="btn primary" id="confirm-move">Move Team</button>
          <button class="btn" id="cancel-move">Cancel</button>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#cancel-move').addEventListener('click', () => backdrop.remove());
    backdrop.querySelector('#confirm-move').addEventListener('click', async () => {
      const roomNum = parseInt(backdrop.querySelector('#target-room-num').value, 10);
      if (isNaN(roomNum) || roomNum < 1) {
        toast('Enter a valid room number', { error: true });
        return;
      }
      try {
        await api.admin.moveTeamRoom(roundId, teamId, roomNum);
        backdrop.remove();
        toast(`Moved ${teamCode} to Room ${roomNum}`);
        loadTeams();
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  const SUIT_SYMBOLS = { SPADE: '♠', HEART: '♥', DIAMOND: '♦', CLUB: '♣' };

  function renderLeaderboard(rows) {
    if (!rows || !rows.length) {
      lbArea.innerHTML = `<div class="empty-state"><div class="empty-icon"><span class="mi">leaderboard</span></div>No results yet. Scores appear after games are played.</div>`;
      return;
    }
    lbArea.innerHTML = `
      <div class="bl-f1-admin-lb-wrapper">
        <div class="bl-f1-header-banner">
          <div class="bl-f1-header-main">
            <span class="bl-f1-brand-tag">ADMIN</span>
            <span class="bl-f1-title-text">LIVE <span class="bl-f1-title-accent">SCOREBOARD</span></span>
          </div>
          <div class="bl-f1-subtitle-text">ROOM STANDINGS</div>
        </div>

        <div class="bl-f1-col-headers" style="grid-template-columns: 46px 1fr auto;">
          <div class="bl-f1-th-pos">POS</div>
          <div class="bl-f1-th-name">TEAM</div>
          <div class="bl-f1-th-scores">
            <span class="bl-f1-th-sc">MM</span>
            <span class="bl-f1-th-sc">AS</span>
            <span class="bl-f1-th-sc">KD</span>
            <span class="bl-f1-th-sc">JH</span>
            <span class="bl-f1-th-total">TOTAL</span>
            <span style="min-width:70px; text-align:center; color:#38bdf8;">STATUS</span>
          </div>
        </div>

        <div class="bl-lb-list">
          ${rows.map((r, idx) => {
            const rank = r.live_rank ?? r.rank ?? (idx + 1);
            const rankNum = `${rank}`;
            const fallbackSuit = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'][idx % 4];
            const suitCode = (r.team_suit_code || r.suit_code || r.suit || fallbackSuit).toUpperCase();
            const suitSymbol = SUIT_SYMBOLS[suitCode] || '♠';
            const mmVal = r.mindmaze_score !== null && r.mindmaze_score !== undefined ? Number(r.mindmaze_score).toFixed(1) : '—';
            const asVal = r.ace_spade_score !== null && r.ace_spade_score !== undefined ? Number(r.ace_spade_score).toFixed(1) : '—';
            const kdVal = r.king_diamond_score !== null && r.king_diamond_score !== undefined ? Number(r.king_diamond_score).toFixed(1) : '—';
            const jhVal = r.jack_heart_score !== null && r.jack_heart_score !== undefined ? Number(r.jack_heart_score).toFixed(1) : '—';
            const totalVal = r.total_score !== null && r.total_score !== undefined ? Number(r.total_score).toFixed(1) : '—';
            const displayName = r.team_code + (r.team_name ? ` (${r.team_name})` : '');
            const statusHtml = r.is_qualified === true 
              ? '<span class="bl-f1-status-pill qualified">QUALIFIED</span>' 
              : r.is_qualified === false 
              ? '<span class="bl-f1-status-pill eliminated">ELIMINATED</span>' 
              : '<span class="bl-f1-status-pill">—</span>';

            return `
              <div class="bl-lb-row suit-${suitCode.toLowerCase()} ${rank === 1 ? 'p1' : ''}">
                <div class="bl-f1-rank-box">
                  <span class="bl-f1-rank-num">${rankNum}</span>
                </div>

                <div class="bl-f1-team-strip suit-bg-${suitCode.toLowerCase()}">
                  <div class="bl-f1-team-text">
                    <span class="bl-f1-team-name">${displayName}</span>
                  </div>
                </div>

                <div class="bl-f1-scores-box">
                  <div class="bl-f1-score-cell" title="MindMaze">${mmVal}</div>
                  <div class="bl-f1-divider">|</div>
                  <div class="bl-f1-score-cell" title="Ace of Spades">${asVal}</div>
                  <div class="bl-f1-divider">|</div>
                  <div class="bl-f1-score-cell" title="King of Diamonds">${kdVal}</div>
                  <div class="bl-f1-divider">|</div>
                  <div class="bl-f1-score-cell" title="Jack of Hearts">${jhVal}</div>
                  <div class="bl-f1-divider">|</div>
                  <div class="bl-f1-score-cell total-score" title="Total Score">${totalVal}</div>
                  <div class="bl-f1-divider">|</div>
                  <div class="bl-f1-suit-cell suit-color-${suitCode.toLowerCase()}">${suitSymbol}</div>
                  <div class="bl-f1-divider">|</div>
                  <div style="min-width: 70px; text-align: center;">${statusHtml}</div>
                </div>
              </div>
            `;
          }).join('')}
        </div>

        <div class="btn-row" style="margin-top: 14px; padding: 0 8px;">
          <button id="recompute-btn" class="btn" style="background: #091322; color: #00ff66; border: 1px solid #1e293b;"><span class="mi">refresh</span> Recompute</button>
        </div>
      </div>
    `;
    lbArea.querySelector('#recompute-btn').addEventListener('click', () => {
      const reBtn = lbArea.querySelector('#recompute-btn');
      if (reBtn) reBtn.disabled = true;
      api.admin.recomputeResults(roomId)
        .then(() => {
          toast('Scores and leaderboard recomputed successfully');
          loadLeaderboard();
          loadSessions();
        })
        .catch(err => toast(err.message, { error: true }))
        .finally(() => {
          if (reBtn) reBtn.disabled = false;
        });
    });
  }

  async function loadLeaderboard() {
    try {
      const rows = await api.admin.roomLeaderboard(roomId).catch(() => null);
      renderLeaderboard(rows);
    } catch (err) {
      lbArea.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
    if (!channel) {
      channel = new LiveChannel(`/rooms/${roomId}/leaderboard`, (data) => renderLeaderboard(data), 'admin');
    }
  }

  async function init() {
    await loadRoomDetails();
    await loadTeams();
    await loadLeaderboard();
    loadDemoNotice();

    // LiveChannel for sessions updates. demo_service publishes to this same
    // channel, so a demo starting or ending refreshes the notice too.
    if (!sessionsChannel) {
      sessionsChannel = new LiveChannel(`/rooms/${roomId}/sessions`, () => {
        loadSessions();
        loadDemoNotice();
      }, 'admin');
    }
  }

  init();

  return () => {
    if (channel) channel.close();
    if (sessionsChannel) sessionsChannel.close();
  };
}
