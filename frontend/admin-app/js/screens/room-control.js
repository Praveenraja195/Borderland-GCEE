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
  const expandedTeams = new Set();

  function renderLeaderboard(rows) {
    if (!rows || !rows.length) {
      lbArea.innerHTML = `<div class="empty-state"><div class="empty-icon"><span class="mi">leaderboard</span></div>No results yet. Scores appear after games are played.</div>`;
      return;
    }

    const allExpanded = rows.length > 0 && rows.every(r => expandedTeams.has(r.team_code));

    lbArea.innerHTML = `
      <div class="bl-admin-scoreboard">
        <div class="bl-sb-header">
          <div class="bl-sb-header-left">
            <span class="bl-sb-live-indicator"><span class="pulse-dot"></span>LIVE STANDINGS</span>
            <div>
              <div class="bl-sb-title">ROOM SCOREBOARD</div>
              <div class="bl-sb-subtitle">${rows.length} Teams Competing • Round-by-Round Breakdown Available</div>
            </div>
          </div>
          <div class="bl-sb-header-actions">
            <button id="toggle-all-btn" class="bl-sb-btn" type="button">
              <span class="mi">${allExpanded ? 'unfold_less' : 'unfold_more'}</span>
              <span>${allExpanded ? 'Collapse All' : 'Expand All Rounds'}</span>
            </button>
            <button id="recompute-btn" class="bl-sb-btn primary" type="button">
              <span class="mi">refresh</span> Recompute
            </button>
          </div>
        </div>

        <div class="bl-sb-table-wrap">
          <table class="bl-sb-table">
            <thead>
              <tr>
                <th class="bl-sb-th center" style="width: 50px;">POS</th>
                <th class="bl-sb-th">TEAM & SUIT</th>
                <th class="bl-sb-th center" title="MindMaze">🧠 MM</th>
                <th class="bl-sb-th center" title="Ace of Spades">♠ AS</th>
                <th class="bl-sb-th center" title="King of Diamonds">♦ KD</th>
                <th class="bl-sb-th center" title="Jack of Hearts">♥ JH</th>
                <th class="bl-sb-th right" style="min-width: 90px;">TOTAL</th>
                <th class="bl-sb-th center" style="min-width: 95px;">STATUS</th>
                <th class="bl-sb-th center" style="width: 100px;">ROUNDS</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map((r, idx) => {
                const rank = r.live_rank ?? r.rank ?? (idx + 1);
                const fallbackSuit = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'][idx % 4];
                const suitCode = (r.team_suit_code || r.suit_code || r.suit || fallbackSuit).toUpperCase();
                const suitSymbol = SUIT_SYMBOLS[suitCode] || '♠';
                const isExpanded = expandedTeams.has(r.team_code);

                const mmVal = r.mindmaze_score !== null && r.mindmaze_score !== undefined ? Number(r.mindmaze_score).toFixed(1) : null;
                const asVal = r.ace_spade_score !== null && r.ace_spade_score !== undefined ? Number(r.ace_spade_score).toFixed(1) : null;
                const kdVal = r.king_diamond_score !== null && r.king_diamond_score !== undefined ? Number(r.king_diamond_score).toFixed(1) : null;
                const jhVal = r.jack_heart_score !== null && r.jack_heart_score !== undefined ? Number(r.jack_heart_score).toFixed(1) : null;
                const totalVal = r.total_score !== null && r.total_score !== undefined ? Number(r.total_score).toFixed(1) : '0.0';

                const statusHtml = r.is_qualified === true 
                  ? '<span class="bl-sb-status-pill qualified">QUALIFIED</span>' 
                  : r.is_qualified === false 
                  ? '<span class="bl-sb-status-pill eliminated">ELIMINATED</span>' 
                  : '<span class="bl-sb-status-pill active">ACTIVE</span>';

                const rankClass = rank === 1 ? 'rank-1' : rank === 2 ? 'rank-2' : rank === 3 ? 'rank-3' : '';
                const details = r.round_details || {};
                const mmRounds = details.MINDMAZE || [];
                const asRounds = details.ACE_SPADE || [];
                const kdRounds = details.KING_DIAMOND || [];
                const jhRounds = details.JACK_HEART || [];

                return `
                  <tr class="bl-sb-row ${isExpanded ? 'expanded' : ''}" data-team-code="${r.team_code}">
                    <td class="bl-sb-td center">
                      <span class="bl-sb-rank-badge ${rankClass}">#${rank}</span>
                    </td>
                    <td class="bl-sb-td">
                      <div class="bl-sb-team-cell">
                        <span class="bl-sb-suit-icon ${suitCode.toLowerCase()}" title="${suitCode}">${suitSymbol}</span>
                        <div>
                          <div class="bl-sb-team-code">${r.team_code}</div>
                          ${r.team_name ? `<div class="bl-sb-team-sub">${r.team_name}</div>` : ''}
                        </div>
                      </div>
                    </td>
                    <td class="bl-sb-td center">
                      <span class="bl-sb-score-pill ${mmVal !== null ? 'active-score' : 'empty'}">${mmVal ?? '—'}</span>
                    </td>
                    <td class="bl-sb-td center">
                      <span class="bl-sb-score-pill ${asVal !== null ? 'active-score' : 'empty'}">${asVal ?? '—'}</span>
                    </td>
                    <td class="bl-sb-td center">
                      <span class="bl-sb-score-pill ${kdVal !== null ? 'active-score' : 'empty'}">${kdVal ?? '—'}</span>
                    </td>
                    <td class="bl-sb-td center">
                      <span class="bl-sb-score-pill ${jhVal !== null ? 'active-score' : 'empty'}">${jhVal ?? '—'}</span>
                    </td>
                    <td class="bl-sb-td right">
                      <div class="bl-sb-total-box">${totalVal}<span class="bl-sb-total-pts">PTS</span></div>
                    </td>
                    <td class="bl-sb-td center">
                      ${statusHtml}
                    </td>
                    <td class="bl-sb-td center">
                      <button class="bl-sb-toggle-btn ${isExpanded ? 'expanded' : ''}" type="button" data-team-toggle="${r.team_code}">
                        <span>${isExpanded ? 'Hide' : 'Details'}</span>
                        <span class="mi">expand_more</span>
                      </button>
                    </td>
                  </tr>

                  <tr class="bl-sb-drawer-row ${isExpanded ? '' : 'hidden'}" id="drawer-${r.team_code}">
                    <td colspan="9" class="bl-sb-drawer-td">
                      <div class="bl-sb-drawer-content">
                        <div class="bl-sb-drawer-title">
                          <span>ROUND-BY-ROUND METRICS FOR <strong>${r.team_code}</strong></span>
                          <span>TOTAL ACCUMULATED: <strong>${totalVal} PTS</strong></span>
                        </div>
                        <div class="bl-sb-games-grid">

                          <!-- King of Diamonds Card -->
                          <div class="bl-sb-game-card">
                            <div class="bl-sb-game-card-header">
                              <span class="bl-sb-game-card-title">♦ King of Diamonds</span>
                              <span class="bl-sb-game-card-score">${kdVal ? `${kdVal} PTS` : '—'}</span>
                            </div>
                            ${kdRounds.length ? `
                              <table class="bl-sb-round-table">
                                <thead>
                                  <tr>
                                    <th>Round</th>
                                    <th class="right">Target</th>
                                    <th class="right">Pick</th>
                                    <th class="right">Diff</th>
                                    <th class="center">Rank</th>
                                    <th class="center">Penalty</th>
                                    <th class="right">Score</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  ${kdRounds.map(kd => `
                                    <tr>
                                      <td><span class="bl-sb-round-badge">R${kd.round_number}</span></td>
                                      <td class="right">${kd.target_value !== null ? Number(kd.target_value).toFixed(2) : '—'}</td>
                                      <td class="right" style="font-weight:700;">${kd.submitted_number !== null ? Number(kd.submitted_number).toFixed(2) : '—'}</td>
                                      <td class="right">${kd.difference !== null ? Number(kd.difference).toFixed(2) : '—'}</td>
                                      <td class="center">
                                        ${kd.rank !== null ? `#${kd.rank}` : '—'}
                                        ${kd.is_winner ? ' <span class="bl-sb-winner-tag">👑 WINNER</span>' : ''}
                                      </td>
                                      <td class="center">
                                        ${kd.penalty > 0 ? `<span class="bl-sb-penalty-tag">-${Number(kd.penalty).toFixed(1)}</span>` : '<span style="color:#16a34a; font-weight:700;">0</span>'}
                                      </td>
                                      <td class="right bl-sb-score-cell">${Number(kd.score).toFixed(1)}</td>
                                    </tr>
                                  `).join('')}
                                </tbody>
                              </table>
                            ` : `<div class="bl-sb-no-rounds">No King of Diamonds rounds played yet.</div>`}
                          </div>

                          <!-- MindMaze Card -->
                          <div class="bl-sb-game-card">
                            <div class="bl-sb-game-card-header">
                              <span class="bl-sb-game-card-title">🧠 MindMaze</span>
                              <span class="bl-sb-game-card-score">${mmVal ? `${mmVal} PTS` : '—'}</span>
                            </div>
                            ${mmRounds.length ? `
                              <table class="bl-sb-round-table">
                                <thead>
                                  <tr>
                                    <th>Round</th>
                                    <th class="center">Moves</th>
                                    <th class="center">Mistakes</th>
                                    <th class="center">Correct</th>
                                    <th class="center">Time</th>
                                    <th class="right">Score</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  ${mmRounds.map(mm => `
                                    <tr>
                                      <td><span class="bl-sb-round-badge">R${mm.round_number}</span></td>
                                      <td class="center">${mm.moves}</td>
                                      <td class="center">${mm.mistakes > 0 ? `<span class="bl-sb-penalty-tag">${mm.mistakes}</span>` : '0'}</td>
                                      <td class="center"><span class="bl-sb-correct-tag">${mm.correct_tiles}</span></td>
                                      <td class="center" style="font-family:monospace;">${mm.completion_time || '—'}</td>
                                      <td class="right bl-sb-score-cell">${Number(mm.score).toFixed(1)}</td>
                                    </tr>
                                  `).join('')}
                                </tbody>
                              </table>
                            ` : `<div class="bl-sb-no-rounds">No MindMaze rounds played yet.</div>`}
                          </div>

                          <!-- Ace of Spades Card -->
                          <div class="bl-sb-game-card">
                            <div class="bl-sb-game-card-header">
                              <span class="bl-sb-game-card-title">♠ Ace of Spades</span>
                              <span class="bl-sb-game-card-score">${asVal ? `${asVal} PTS` : '—'}</span>
                            </div>
                            ${asRounds.length ? `
                              <table class="bl-sb-round-table">
                                <thead>
                                  <tr>
                                    <th>Round</th>
                                    <th class="center">Moves</th>
                                    <th class="center">Correct</th>
                                    <th class="center">Wrong</th>
                                    <th class="center">Time</th>
                                    <th class="right">Score</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  ${asRounds.map(as_item => `
                                    <tr>
                                      <td><span class="bl-sb-round-badge">R${as_item.round_number}</span></td>
                                      <td class="center">${as_item.moves}</td>
                                      <td class="center"><span class="bl-sb-correct-tag">${as_item.correct_picks}</span></td>
                                      <td class="center">${as_item.wrong_picks > 0 ? `<span class="bl-sb-penalty-tag">${as_item.wrong_picks}</span>` : '0'}</td>
                                      <td class="center" style="font-family:monospace;">${as_item.completion_time || '—'}</td>
                                      <td class="right bl-sb-score-cell">${Number(as_item.score).toFixed(1)}</td>
                                    </tr>
                                  `).join('')}
                                </tbody>
                              </table>
                            ` : `<div class="bl-sb-no-rounds">No Ace of Spades rounds played yet.</div>`}
                          </div>

                          <!-- Jack of Hearts Card -->
                          <div class="bl-sb-game-card">
                            <div class="bl-sb-game-card-header">
                              <span class="bl-sb-game-card-title">♥ Jack of Hearts</span>
                              <span class="bl-sb-game-card-score">${jhVal ? `${jhVal} PTS` : '—'}</span>
                            </div>
                            ${jhRounds.length ? `
                              <table class="bl-sb-round-table">
                                <thead>
                                  <tr>
                                    <th>Round</th>
                                    <th>Guessed</th>
                                    <th>Actual</th>
                                    <th class="center">Result</th>
                                    <th class="right">Score</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  ${jhRounds.map(jh => `
                                    <tr>
                                      <td><span class="bl-sb-round-badge">R${jh.round_number}</span></td>
                                      <td style="font-weight:700;">${jh.submitted_symbol || '—'}</td>
                                      <td style="color:#64748b;">${jh.actual_symbol || '—'}</td>
                                      <td class="center">
                                        ${jh.is_correct ? '<span class="bl-sb-correct-tag">✓ CORRECT</span>' : '<span class="bl-sb-wrong-tag">✕ WRONG</span>'}
                                      </td>
                                      <td class="right bl-sb-score-cell">${Number(jh.score).toFixed(1)}</td>
                                    </tr>
                                  `).join('')}
                                </tbody>
                              </table>
                            ` : `<div class="bl-sb-no-rounds">No Jack of Hearts rounds played yet.</div>`}
                          </div>

                        </div>
                      </div>
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

    // Row expansion click handlers
    lbArea.querySelectorAll('.bl-sb-row').forEach(row => {
      row.addEventListener('click', (e) => {
        // Prevent toggle if clicking a link or button directly
        if (e.target.closest('button') && !e.target.closest('.bl-sb-toggle-btn')) return;
        const code = row.getAttribute('data-team-code');
        if (!code) return;
        if (expandedTeams.has(code)) {
          expandedTeams.delete(code);
        } else {
          expandedTeams.add(code);
        }
        renderLeaderboard(rows);
      });
    });

    // Toggle all button
    const toggleAllBtn = lbArea.querySelector('#toggle-all-btn');
    if (toggleAllBtn) {
      toggleAllBtn.addEventListener('click', () => {
        if (allExpanded) {
          expandedTeams.clear();
        } else {
          rows.forEach(r => expandedTeams.add(r.team_code));
        }
        renderLeaderboard(rows);
      });
    }

    // Recompute button
    const recomputeBtn = lbArea.querySelector('#recompute-btn');
    if (recomputeBtn) {
      recomputeBtn.addEventListener('click', () => {
        recomputeBtn.disabled = true;
        api.admin.recomputeResults(roomId)
          .then(() => {
            toast('Scores and leaderboard recomputed successfully');
            loadLeaderboard();
            loadSessions();
          })
          .catch(err => toast(err.message, { error: true }))
          .finally(() => {
            recomputeBtn.disabled = false;
          });
      });
    }
  }

  async function loadLeaderboard() {
    try {
      const rows = await api.admin.roomLeaderboard(roomId).catch(() => null);
      renderLeaderboard(rows);
    } catch (err) {
      lbArea.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
    if (!channel) {
      channel = new LiveChannel(`/rooms/${roomId}/leaderboard`, async () => {
        try {
          const fresh = await api.admin.roomLeaderboard(roomId);
          if (fresh) renderLeaderboard(fresh);
        } catch (_) {}
      }, 'admin');
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
