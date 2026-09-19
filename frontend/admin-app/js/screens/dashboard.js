import { api } from '../../../shared/js/api.js';
import { openWinnersModal } from './winners-export.js';
import { GAMES } from '../../../shared/js/copy.js';
import { toast } from '../../../shared/js/ui.js';

const ALL_GAMES = ['MINDMAZE', 'ACE_SPADE', 'KING_DIAMOND', 'JACK_HEART'];

// Map game codes to icon colors for service cards
const GAME_ICONS = {
  MINDMAZE:     { icon: 'psychology', color: 'blue' },
  ACE_SPADE:    { icon: 'style',      color: 'ink' },
  KING_DIAMOND: { icon: 'diamond',    color: 'amber' },
  JACK_HEART:   { icon: 'favorite',   color: 'red' },
};

export function renderDashboard(root, navigate, role) {
  let pollInterval = null;

  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Dashboard</h1>
    </div>
    <div id="dash-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#dash-body');
  let roundData = null;

  async function load(silent = false) {
    if (!silent) {
      body.innerHTML = `<div class="spinner"></div>`;
    }
    const topline = root.querySelector('.admin-topline');
    try {
      const rounds = await api.admin.listRounds();
      if (!rounds.length) {
        roundData = null;
        topline.innerHTML = `<h1 class="admin-h1">Dashboard</h1>`;
        renderNoRound();
        return;
      }
      // Use the first (and only) round
      const roundSummary = rounds[0];
      const [detail, gameSessions, demoSessions] = await Promise.all([
        api.admin.getRound(roundSummary.round_id),
        api.admin.getRoundGameSessions(roundSummary.round_id).catch(() => []),
        api.admin.demo.list(roundSummary.round_id).catch(() => []),
      ]);
      roundData = detail;

      if (!silent || !topline.querySelector('#reset-event-btn')) {
        topline.innerHTML = `<h1 class="admin-h1">Dashboard</h1>`;
        if (role === 'SUPER_ADMIN') {
          const resetBtn = document.createElement('button');
          resetBtn.className = 'btn danger';
          resetBtn.id = 'reset-event-btn';
          resetBtn.style.marginLeft = 'auto';
          resetBtn.innerHTML = '<span class="mi">restart_alt</span> Reset Event';
          topline.appendChild(resetBtn);
          resetBtn.addEventListener('click', () => {
            openResetEventModal(detail.round_id, detail.name || `Round ${detail.round_number}`);
          });
        }
        renderDashboardContent(detail, gameSessions, demoSessions);
      } else {
        const gameControlsEl = body.querySelector('#game-controls');
        if (gameControlsEl) renderGameControls(gameControlsEl, detail, gameSessions, demoSessions);
      }
    } catch (err) {
      if (!silent) {
        body.innerHTML = `<p class="status-note error">${err.message}</p>`;
      }
    }
  }

  function openResetEventModal(roundId, roundName) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal" style="max-width: 520px; border-top: 4px solid var(--bl-red, #dc2626);">
        <div style="display:flex; align-items:flex-start; gap:14px; margin-bottom:16px;">
          <div style="width:48px; height:48px; border-radius:12px; background:#fee2e2; border:1px solid #fca5a5; color:#dc2626; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
            <span class="mi" style="font-size:28px;">warning</span>
          </div>
          <div>
            <h3 style="margin:0 0 4px 0; font-size:1.15rem; color:#0f172a; font-weight:900;">Reset Event & Start Fresh?</h3>
            <p style="margin:0; font-size:0.8rem; color:#64748b;">
              This will completely wipe <strong>${roundName || 'Round 1'}</strong> and all game data.
            </p>
          </div>
        </div>

        <div style="background:#fff1f2; border:1px solid #fecdd3; border-radius:8px; padding:12px 14px; margin-bottom:16px; font-size:0.78rem; color:#9f1239; line-height:1.5;">
          <div style="font-weight:800; margin-bottom:6px; display:flex; align-items:center; gap:6px;">
            <span class="mi" style="font-size:16px;">delete_forever</span> This action will permanently erase:
          </div>
          <ul style="margin:0; padding-left:18px;">
            <li>All rooms, room assignments, and game sessions</li>
            <li>All team selections, player answers, and scores across all 4 games</li>
            <li>Final qualification rankings and leaderboard results</li>
          </ul>
          <div style="margin-top:8px; font-weight:700; color:#059669; display:flex; align-items:center; gap:4px;">
            <span class="mi" style="font-size:15px;">check_circle</span> Registered teams & logins will be preserved.
          </div>
        </div>

        <div style="display:flex; align-items:center; justify-content:flex-end; gap:10px;">
          <button type="button" class="btn" id="modal-cancel-reset-btn" style="padding:8px 16px;">Cancel</button>
          <button type="button" class="btn danger" id="modal-confirm-reset-btn" style="padding:8px 20px; font-weight:800; background:#dc2626; color:#fff;">
            <span class="mi">restart_alt</span> Wipe Event & Start Fresh
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(backdrop);

    const cancelBtn = backdrop.querySelector('#modal-cancel-reset-btn');
    const confirmBtn = backdrop.querySelector('#modal-confirm-reset-btn');

    cancelBtn.onclick = () => backdrop.remove();
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });

    confirmBtn.onclick = async () => {
      confirmBtn.disabled = true;
      cancelBtn.disabled = true;
      confirmBtn.innerHTML = '<span class="mi spin">autorenew</span> Wiping event...';
      try {
        await api.admin.deleteRound(roundId);
        backdrop.remove();
        toast('🎉 Event wiped successfully! You can now start fresh.');
        roundData = null;
        load();
      } catch (err) {
        toast(err.message, { error: true });
        confirmBtn.disabled = false;
        cancelBtn.disabled = false;
        confirmBtn.innerHTML = '<span class="mi">restart_alt</span> Wipe Event & Start Fresh';
      }
    };
  }


  function renderNoRound() {
    body.innerHTML = `
      <div class="stats-row">
        <div class="stat-card accent-blue">
          <div class="stat-icon"><span class="mi">groups</span></div>
          <div class="stat-label">Teams Registered</div>
          <div class="stat-value" id="team-count-stat">...</div>
        </div>
        <div class="stat-card accent-amber">
          <div class="stat-icon"><span class="mi">info</span></div>
          <div class="stat-label">Status</div>
          <div class="stat-value" style="font-size:0.88rem;">No round created</div>
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

    // Load team count
    api.admin.teams.list().then(teams => {
      const el = body.querySelector('#team-count-stat');
      if (el) el.textContent = teams.length;
    }).catch(() => { });

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

  function renderDashboardContent(detail, gameSessions = [], demoSessions = []) {

    const roomCount = detail.rooms?.length || 0;
    const totalTeams = detail.rooms?.reduce((sum, r) => sum + (r.team_count || 0), 0) || 0;

    const configuredGames = (detail.games && detail.games.length > 0)
      ? detail.games.map(g => g.code)
      : (gameSessions.length > 0
          ? [...new Set(gameSessions.map(s => s.game_code || s.session?.game_code).filter(Boolean))]
          : ALL_GAMES);

    // Determine if all games in all rooms are completed and if all are published
    let allGamesCompleted = configuredGames.length > 0;
    let allGamesPublished = gameSessions.length > 0;

    for (const code of configuredGames) {
      const sessList = gameSessions.filter(s => s.game_code === code || s.session?.game_code === code);
      if (!sessList.length) {
        allGamesCompleted = false;
        allGamesPublished = false;
        continue;
      }
      for (const s of sessList) {
        const sessionObj = s.session || s;
        if (!sessionObj.is_published) allGamesPublished = false;
        const rList = s.rounds || sessionObj.rounds || [];
        const isSessionFinished = sessionObj.status === 'COMPLETED' || (rList.length > 0 && rList.every(r => r.is_closed || (r.deadline && new Date(r.deadline) <= new Date())));
        if (!isSessionFinished) {
          allGamesCompleted = false;
        }
      }
    }

    body.innerHTML = `
      <div class="stats-row">
        <div class="stat-card accent-ink">
          <div class="stat-icon"><span class="mi">trophy</span></div>
          <div class="stat-label">Round</div>
          <div class="stat-value">
            ${detail.name}
            <span class="pill ${detail.status}">${detail.status?.replace('_', ' ')}</span>
          </div>
        </div>
        <div class="stat-card accent-blue clickable" id="rooms-stat-card" title="View all rooms">
          <div class="stat-icon"><span class="mi">meeting_room</span></div>
          <div class="stat-label">Rooms</div>
          <div class="stat-value">
            ${roomCount}
            <span class="stat-meta"><span class="mi" style="font-size:14px;">arrow_forward</span> View</span>
          </div>
        </div>
        <div class="stat-card accent-green">
          <div class="stat-icon"><span class="mi">toggle_on</span></div>
          <div class="stat-label">Round Control</div>
          <div class="stat-value">
            ${detail.status === 'NOT_STARTED' ? '<button class="btn success" id="activate-round-btn"><span class="mi">play_arrow</span> Activate</button>' : ''}
            ${detail.status === 'ACTIVE' ? '<button class="btn danger" id="complete-round-btn"><span class="mi">flag</span> Complete</button>' : ''}
            ${detail.status === 'COMPLETED' ? '<span style="display:flex;align-items:center;gap:5px;font-size:0.85rem;"><span class="mi" style="color:#059669;">check_circle</span> Complete</span>' : ''}
          </div>
        </div>
      </div>

      <!-- Main Dashboard Publish Final Results to All Teams -->
      <div class="publish-final-results-card ${allGamesCompleted ? 'ready' : 'locked'}" style="margin: 16px 0 24px; padding: 18px 20px; background: ${allGamesPublished ? '#ecfdf5' : allGamesCompleted ? '#eff6ff' : '#f8fafc'}; border: 1.5px solid ${allGamesPublished ? '#10b981' : allGamesCompleted ? '#3b82f6' : '#cbd5e1'}; border-radius: 12px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;">
        <div style="display: flex; align-items: center; gap: 14px;">
          <div style="width: 44px; height: 44px; border-radius: 10px; background: ${allGamesPublished ? '#059669' : allGamesCompleted ? '#2563eb' : '#94a3b8'}; color: #fff; display: flex; align-items: center; justify-content: center; font-size: 24px;">
            <span class="mi">${allGamesPublished ? 'verified' : allGamesCompleted ? 'campaign' : 'lock'}</span>
          </div>
          <div>
            <div style="font-weight: 800; font-size: 1rem; color: #0f172a;">
              Publish Final Results to All Teams / 全チームに結果公開
            </div>
            <div style="font-size: 0.82rem; color: #64748b; margin-top: 2px;">
              ${allGamesPublished 
                ? '✅ Final results and Round 2 qualifications are active across all team devices!' 
                : allGamesCompleted 
                  ? '🎉 All games finished across all rooms! Ready to broadcast final results to all teams.' 
                  : '⚠️ Some games or subrounds have not been completed yet across rooms. (Broadcast will finalize & publish)'}
            </div>
          </div>
        </div>

        <div class="btn-row">
          <button class="btn ${allGamesPublished ? 'success' : 'success solid'}" id="publish-final-all-btn">
            <span class="mi">${allGamesPublished ? 'sensors' : 'campaign'}</span>
            ${allGamesPublished ? 'Broadcast Live Results / View Status' : 'Publish Final Results to All Teams'}
          </button>
          <!-- Deliberately never disabled: an organiser often wants the
               qualifier list in hand *before* announcing it, and the export
               recomputes room results itself, so it is always current. -->
          <button class="btn" id="export-winners-btn" title="Round 2 qualifier list as an .xlsx you can forward">
            <span class="mi">download</span>
            Export Round 2 Qualifiers
          </button>
        </div>
      </div>

      <div id="tiebreak-section"></div>

      <div class="section-divider"><span class="mi">sports_esports</span> Game Services</div>
      <div class="game-controls" id="game-controls"></div>
    `;

    const roomsStatCard = body.querySelector('#rooms-stat-card');
    if (roomsStatCard) {
      roomsStatCard.addEventListener('click', () => navigate('#/rooms'));
    }

    const exportWinnersBtn = body.querySelector('#export-winners-btn');
    if (exportWinnersBtn) {
      exportWinnersBtn.addEventListener('click', () => {
        openWinnersModal(detail.round_id, `Round ${detail.round_number} — ${detail.name}`);
      });
    }

    // Wire main dashboard publish all button to open dedicated live broadcast modal
    const publishFinalAllBtn = body.querySelector('#publish-final-all-btn');
    if (publishFinalAllBtn) {
      publishFinalAllBtn.addEventListener('click', () => {
        openPublishFinalResultsModal(detail.round_id, detail, allGamesCompleted);
      });
    }

    // Wire round status buttons
    const activateBtn = body.querySelector('#activate-round-btn');
    if (activateBtn) {
      activateBtn.addEventListener('click', async () => {
        activateBtn.disabled = true;
        const originalHtml = activateBtn.innerHTML;
        activateBtn.innerHTML = '<span class="mi spin">autorenew</span> Activating...';
        try {
          await api.admin.setRoundStatus(detail.round_id, 'ACTIVE');
          toast('🎉 Round 1 activated! Teams can now play.');
          load();
        } catch (err) {
          toast(err.message, { error: true });
          activateBtn.disabled = false;
          activateBtn.innerHTML = originalHtml;
        }
      });
    }
    const completeBtn = body.querySelector('#complete-round-btn');
    if (completeBtn) {
      completeBtn.addEventListener('click', async () => {
        completeBtn.disabled = true;
        const originalHtml = completeBtn.innerHTML;
        completeBtn.innerHTML = '<span class="mi spin">autorenew</span> Completing...';
        try {
          await api.admin.setRoundStatus(detail.round_id, 'COMPLETED');
          toast('Round 1 completed!');
          load();
        } catch (err) {
          toast(err.message, { error: true });
          completeBtn.disabled = false;
          completeBtn.innerHTML = originalHtml;
        }
      });
    }

    renderGameControls(body.querySelector('#game-controls'), detail, gameSessions, demoSessions);
    lastTiebreakJson = '';
    refreshTiebreaks();
  }

  function renderGameControls(el, detail, gameSessions = [], demoSessions = []) {
    el.innerHTML = ALL_GAMES.map(code => {
      const gi = GAME_ICONS[code] || { icon: 'casino', color: 'blue' };
      const sessList = gameSessions.filter(s => s.game_code === code || s.session?.game_code === code);
      const sessionObj = sessList.length ? (sessList[0].session || sessList[0]) : null;
      let subrounds = [];
      if (sessList.length) {
        for (const s of sessList) {
          const rList = s.rounds || s.session?.rounds || [];
          if (rList.length > 0) {
            subrounds = rList;
            break;
          }
        }
      }
      const hasSession = !!sessionObj && subrounds.length > 0;

      // Determine overall game status
      const allFinished = subrounds.length > 0 && subrounds.every(r => r.is_closed || (r.deadline && new Date(r.deadline) <= new Date()));
      const hasActive = subrounds.some(r => r.start_time && !r.is_closed && !(r.deadline && new Date(r.deadline) <= new Date()));

      const statusDotHtml = allFinished
        ? '<span class="status-dot blue"></span>'
        : hasActive
          ? '<span class="status-dot green pulse"></span>'
          : hasSession
            ? '<span class="status-dot amber"></span>'
            : '<span class="status-dot gray"></span>';

      // --- Completion banner (only CTA for Publish — no duplicate in action bar) ---
      const completionBannerHtml = allFinished ? `
        <div class="completion-banner">
          <div class="cb-text">
            <div class="cb-title"><span class="mi">celebration</span> All sub-rounds finished!</div>
            <div class="cb-sub">Publish the final room leaderboards to team screens.</div>
          </div>
          <button class="btn success solid" data-act="publish" data-game="${code}">
            <span class="mi">cast</span> Publish Results
          </button>
        </div>
      ` : '';

      // --- Sub-round rows ---
      const subroundRowsHtml = subrounds.length > 0 ? `
        <div class="subround-list">
          <div class="subround-list-header">
            <span>Sub-Round</span>
            <span>Actions</span>
          </div>
          ${subrounds.map((r, idx) => {
            const isStarted = !!r.start_time;
            const isClosed = !!r.is_closed || (r.deadline && new Date(r.deadline) <= new Date());
            const precStarted = idx === 0 ? true : !!(subrounds[idx - 1] && subrounds[idx - 1].start_time);
            const canStart = precStarted && !isStarted && !isClosed;

            const badgeClass = isClosed ? 'completed' : isStarted ? 'active' : 'not-started';
            const badgeText = isClosed ? 'Completed' : isStarted ? 'Active' : 'Not Started';
            const dotColor = isClosed ? 'blue' : isStarted ? 'green pulse' : 'gray';

            let actionsHtml = '';
            if (isClosed) {
              actionsHtml = `<button class="btn danger" data-act="restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">refresh</span> Restart</button>`;
            } else if (isStarted) {
              actionsHtml = `<button class="btn danger" data-act="restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">refresh</span> Restart</button>`;
            } else {
              actionsHtml = `<button class="btn primary" data-act="start-subround" data-game="${code}" data-subround="${r.round_number}" ${!canStart ? 'disabled' : ''}><span class="mi">play_arrow</span> Start</button>`;
            }

            return `
              <div class="subround-row">
                <div class="sr-info">
                  <span class="status-dot ${dotColor}"></span>
                  Sub-Round ${r.round_number}
                  <span class="sr-badge ${badgeClass}">${badgeText}</span>
                </div>
                <div class="sr-actions">${actionsHtml}</div>
              </div>
            `;
          }).join('')}
        </div>
      ` : `<div class="subround-empty">No active session — click "Start Session" to begin.</div>`;

      // --- Service Card ---
      return `
        <div class="svc-card">
          <div class="svc-card-header">
            <div class="svc-card-title">
              <div class="svc-icon ${gi.color}"><span class="mi">${gi.icon}</span></div>
              ${GAMES[code]?.en || code}
              ${statusDotHtml}
            </div>
            <button class="btn success" data-act="instructions" data-game="${code}">
              <span class="mi">campaign</span> Broadcast Rules
            </button>
          </div>
          <div class="action-bar">
            <button class="btn primary" data-act="start" data-game="${code}" ${hasSession ? 'disabled' : ''}>
              <span class="mi">play_circle</span> Start Session
            </button>
            <span class="action-divider"></span>
            <button class="btn" data-act="show-results" data-game="${code}" ${!hasSession ? 'disabled' : ''}>
              <span class="mi">monitoring</span> Progress
            </button>
            <button class="btn danger" data-act="restart" data-game="${code}" ${!hasSession ? 'disabled' : ''}>
              <span class="mi">restart_alt</span> Restart All
            </button>
          </div>
          <div class="svc-card-body">
            ${completionBannerHtml}
            ${renderDemoPanel(code, demoSessions)}
            ${subroundRowsHtml}
          </div>
        </div>
      `;
    }).join('');



    // Wire action buttons
    el.querySelectorAll('[data-act]').forEach(btn => {
      const act = btn.dataset.act;
      const code = btn.dataset.game;
      btn.addEventListener('click', () => {
        if (act === 'start') {
          openStartModal(code, detail.round_id);
        } else if (act === 'start-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.startSubroundForRound(detail.round_id, code, subnum)
            .then(res => { toast(`Sub-round ${subnum} started in ${res.succeeded.length} rooms!`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'restart-subround') {
          const subnum = Number(btn.dataset.subround);
          if (!confirm(`Restart Sub-Round ${subnum} for ${GAMES[code]?.en} in ALL rooms? This resets ONLY Sub-Round ${subnum} so it can be re-played.`)) return;
          api.admin.restartSubroundForRound(detail.round_id, code, subnum)
            .then(res => { toast(`Sub-round ${subnum} restarted in ${res.succeeded.length} rooms!`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'publish') {
          btn.disabled = true;
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<span class="mi spin">autorenew</span> Publishing...';
          api.admin.publishGameForRound(detail.round_id, code)
            .then(() => {
              toast(`Published ${GAMES[code]?.en || code} results to all teams in all rooms!`);
              load();
            })
            .catch(err => {
              toast(err.message, { error: true });
              btn.disabled = false;
              btn.innerHTML = originalHtml;
            });
        } else if (act === 'show-results') {
          openResultsModal(code, detail.round_id, gameSessions);
        } else if (act === 'next-subround') {
          api.admin.startNextSubroundForRound(detail.round_id, code)
            .then(res => { toast(`Started next sub-round in ${res.succeeded.length} rooms!`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'instructions') {
          btn.disabled = true;
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<span class="mi spin">autorenew</span> Broadcasting...';
          api.admin.showInstructionsForRound(detail.round_id, code)
            .then(res => { toast(`Rules broadcasted successfully to all rooms!`); load(); })
            .catch(err => {
              toast(err.message, { error: true });
              btn.disabled = false;
              btn.innerHTML = originalHtml;
            });
        } else if (act === 'pause') {
          btn.disabled = true;
          api.admin.pauseSessionsForRound(detail.round_id, code)
            .then(res => { toast(`Paused in ${res.succeeded.length} rooms`); load(); })
            .catch(err => { toast(err.message, { error: true }); btn.disabled = false; });
        } else if (act === 'resume') {
          btn.disabled = true;
          api.admin.resumeSessionsForRound(detail.round_id, code)
            .then(res => { toast(`Resumed in ${res.succeeded.length} rooms`); load(); })
            .catch(err => { toast(err.message, { error: true }); btn.disabled = false; });
        } else if (act === 'complete') {
          btn.disabled = true;
          const originalHtml = btn.innerHTML;
          btn.innerHTML = '<span class="mi spin">autorenew</span> Completing...';
          api.admin.forceCompleteSessionsForRound(detail.round_id, code)
            .then(() => api.admin.publishGameForRound(detail.round_id, code))
            .then(() => { toast(`Results revealed and published to all team screens!`); load(); })
            .catch(err => {
              toast(err.message, { error: true });
              btn.disabled = false;
              btn.innerHTML = originalHtml;
            });
        } else if (act === 'restart') {
          if (!confirm(`RESTART ${GAMES[code]?.en} in ALL rooms? This wipes all score data!`)) return;
          api.admin.restartSessionsForRound(detail.round_id, code)
            .then(res => { toast(`Restarted in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-start') {
          openDemoStartModal(code, detail.round_id);
        } else if (act === 'demo-restart') {
          // The practice-again control: deals a fresh attempt from any
          // state. No confirm — being able to hit it repeatedly without
          // friction is the whole point of a practice round.
          api.admin.demo.restart(detail.round_id, code)
            .then(res => { toast(`New demo attempt dealt in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-end') {
          if (!confirm(`End the ${GAMES[code]?.en || code} demo in ALL rooms? Team screens return to the real game.`)) return;
          api.admin.demo.end(detail.round_id, code)
            .then(res => { toast(`Demo ended in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-pause') {
          api.admin.demo.pause(detail.round_id, code)
            .then(res => { toast(`Demo paused in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-resume') {
          api.admin.demo.resume(detail.round_id, code)
            .then(res => { toast(`Demo resumed in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-start-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.demo.startSubround(detail.round_id, code, subnum)
            .then(res => { toast(`Demo sub-round ${subnum} started in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        } else if (act === 'demo-restart-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.demo.restartSubround(detail.round_id, code, subnum)
            .then(res => { toast(`Demo sub-round ${subnum} replayed in ${res.succeeded.length} rooms`); load(); })
            .catch(err => toast(err.message, { error: true }));
        }
      });
    });
  }

  /* ======================================================================
     Demo (practice) rounds
     ----------------------------------------------------------------------
     A parallel play surface teams can rehearse on, living entirely in Redis
     (see app/services/demo_service.py) — nothing played here reaches
     game_scores, the per-game result tables, room_results, or any
     leaderboard. Start it, replay it as often as the room needs, then end
     it to hand the team screens back to the real game.

     Mirrors the panel on the round-detail screen; both drive the same
     api.admin.demo.* endpoints.
     ====================================================================== */

  function renderDemoPanel(code, demoSessions = []) {
    const demos = (demoSessions || []).filter(d => d.game_code === code);
    const live = demos.length > 0;

    if (!live) {
      return `
        <div class="demo-panel">
          <div class="demo-panel-head">
            <span class="demo-tag">DEMO</span>
            <span class="demo-title">Practice Round</span>
            <span class="demo-status idle">Not running</span>
            <button class="btn primary demo-panel-cta" data-act="demo-start" data-game="${code}">
              <span class="mi">school</span> Start Demo
            </button>
          </div>
          <p class="demo-note">Let teams rehearse on the real game screens. Nothing they score is saved.</p>
        </div>
      `;
    }

    // Every room in a round is dealt the same demo shape, so the first is a
    // fair representative for the sub-round list; counts are still summed
    // across every room.
    const subrounds = demos[0].rounds || [];
    const attempt = Math.max(...demos.map(d => d.attempt || 1));
    const statuses = new Set(demos.map(d => d.status));
    const isPaused = statuses.has('PAUSED');
    const isCompleted = [...statuses].every(st => st === 'COMPLETED');
    const totalTeams = demos.reduce((sum, d) => sum + (d.total_room_teams || 0), 0);

    const statusLabel = isPaused ? 'Paused' : isCompleted ? 'Finished' : 'Running';
    const statusClass = isPaused ? 'paused' : isCompleted ? 'done' : 'running';

    const subroundRows = subrounds.map(r => {
      const submitted = demos.reduce((sum, d) => {
        const match = (d.rounds || []).find(x => x.round_number === r.round_number);
        return sum + ((match && match.submitted_teams) ? match.submitted_teams.length : 0);
      }, 0);
      const started = !!r.start_time;

      const badge = r.is_closed
        ? '<span class="demo-sr-badge done">DONE</span>'
        : started
          ? '<span class="demo-sr-badge live">LIVE</span>'
          : '<span class="demo-sr-badge waiting">WAITING</span>';

      const action = started
        ? `<button class="btn" data-act="demo-restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">replay</span> Replay</button>`
        : `<button class="btn" data-act="demo-start-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">play_arrow</span> Start</button>`;

      return `
        <div class="demo-sr-row">
          <div class="demo-sr-info">
            <span class="demo-sr-name">Sub-Round ${r.round_number}</span>
            ${badge}
            <span class="demo-sr-count">${submitted} / ${totalTeams} submitted</span>
          </div>
          <div class="demo-sr-actions">${action}</div>
        </div>
      `;
    }).join('');

    return `
      <div class="demo-panel live">
        <div class="demo-panel-head">
          <span class="demo-tag">DEMO</span>
          <span class="demo-title">Practice Round</span>
          <span class="demo-status ${statusClass}">${statusLabel}</span>
          ${attempt > 1 ? `<span class="demo-attempt">Attempt ${attempt}</span>` : ''}
          <span class="demo-scope">${demos.length} room${demos.length === 1 ? '' : 's'} &middot; ${totalTeams} teams</span>
        </div>
        <div class="demo-actions">
          <button class="btn primary" data-act="demo-restart" data-game="${code}"><span class="mi">replay</span> Practice Again</button>
          ${isPaused
            ? `<button class="btn" data-act="demo-resume" data-game="${code}"><span class="mi">play_arrow</span> Resume</button>`
            : `<button class="btn" data-act="demo-pause" data-game="${code}"><span class="mi">pause</span> Pause</button>`}
          <button class="btn danger" data-act="demo-end" data-game="${code}"><span class="mi">stop_circle</span> End Demo</button>
        </div>
        <p class="demo-note">Teams see this instead of the real game until you end it. Scores are <strong>never saved</strong>.</p>
        <div class="demo-sr-list">${subroundRows}</div>
      </div>
    `;
  }

  // ── Death Card tiebreakers ─────────────────────────────────────────────
  // Present only when publish found a tie at a room's qualification cutoff.
  // The server runs the rounds itself once started (each device poll advances
  // it); these controls just start it, force a reveal, or reset it.
  let tiebreakPoll = null;
  let tiebreakBusy = false;
  let lastTiebreakJson = '';

  function tbTimeLeft(iso) {
    return Math.max(0, Math.ceil((new Date(iso).getTime() - Date.now()) / 1000));
  }

  function renderTiebreakCard(sess) {
    const rnd = sess.current_round;
    const alive = sess.participants.filter(p => p.status === 'ALIVE').length;
    let statusPill;
    if (sess.status === 'COMPLETED') {
      statusPill = `<span class="pill COMPLETED">● RESOLVED · ${sess.winner_team_codes.join(', ')} through</span>`;
    } else if (sess.status === 'ACTIVE' && rnd && !rnd.is_resolved) {
      statusPill = `<span class="pill IN_PROGRESS">● ROUND ${rnd.round_number} · ${tbTimeLeft(rnd.deadline)}s</span>`;
    } else if (sess.status === 'ACTIVE') {
      statusPill = `<span class="pill ACTIVE">● ROUND ${rnd ? rnd.round_number : ''} REVEALED · next in a moment</span>`;
    } else {
      statusPill = `<span class="pill NOT_STARTED">● WAITING TO START</span>`;
    }

    const chips = sess.participants.map(p => `
      <span class="tb-a-chip ${p.status.toLowerCase()}">
        ${p.team_code}${p.status === 'ELIMINATED' ? ` · out R${p.eliminated_in_round}` : p.status === 'WINNER' ? ' · through' : ''}
      </span>`).join('');

    let cards = '';
    if (rnd) {
      const byIdx = new Map(rnd.picks.map(pk => [pk.card_index, pk]));
      cards = `<div class="tb-a-cards">${Array.from({ length: rnd.card_count }, (_, i) => {
        const pk = byIdx.get(i);
        const isJoker = rnd.is_resolved && rnd.joker_index === i;
        return `
          <div class="tb-a-card ${pk ? 'taken' : ''} ${rnd.is_resolved ? (isJoker ? 'joker' : 'safe') : ''}" title="Card ${i + 1}">
            <div class="tb-a-card-face">${rnd.is_resolved ? (isJoker ? '🃏' : '·') : (pk ? '✓' : '?')}</div>
            <div class="tb-a-card-who">${pk ? pk.team_code + (pk.auto_assigned ? ' (auto)' : '') : '—'}</div>
          </div>`;
      }).join('')}</div>`;
    }

    const history = sess.rounds.length
      ? `<div class="tb-a-history">${sess.rounds.map(r => `<span>R${r.round_number}: ${r.eliminated_team_code ? `<strong>${r.eliminated_team_code}</strong> drew the Joker` : 'no Joker drawn'}</span>`).join('')}</div>`
      : '';

    let actions = '';
    if (sess.status === 'PENDING') {
      actions += `<button class="btn primary" data-tb-act="start" data-tb-id="${sess.session_id}"><span class="mi">play_arrow</span> Start tiebreaker</button>`;
    } else if (sess.status === 'ACTIVE' && rnd && !rnd.is_resolved) {
      actions += `<button class="btn" data-tb-act="advance" data-tb-id="${sess.session_id}"><span class="mi">visibility</span> Reveal now</button>`;
    } else if (sess.status === 'ACTIVE') {
      actions += `<button class="btn" data-tb-act="advance" data-tb-id="${sess.session_id}"><span class="mi">skip_next</span> Next round now</button>`;
    }
    if (role === 'SUPER_ADMIN') {
      actions += `<button class="btn danger" data-tb-act="reset" data-tb-id="${sess.session_id}"><span class="mi">restart_alt</span> Reset</button>`;
    }

    return `
      <div class="svc-card tb-a-card-wrap">
        <div class="svc-card-header">
          <div class="svc-card-title">
            <div class="svc-icon red"><span class="mi">style</span></div>
            Room ${sess.room_code} · Death Card
          </div>
          ${statusPill}
        </div>
        <div class="svc-card-body">
          <div class="tb-a-meta">
            ${sess.participants.length} teams tied at <strong>${Number(sess.tie_total).toFixed(1)} pts</strong>
            for <strong>${sess.slots}</strong> place${sess.slots === 1 ? '' : 's'} · ${alive} still in
          </div>
          <div class="tb-a-chips">${chips}</div>
          ${cards}
          ${history}
          <div class="btn-row" style="margin-top:12px;">${actions}</div>
        </div>
      </div>`;
  }

  function renderTiebreakSection(sessions) {
    const el = body.querySelector('#tiebreak-section');
    if (!el) return;
    if (!sessions || !sessions.length) { el.innerHTML = ''; return; }
    el.innerHTML = `
      <div class="section-divider"><span class="mi">style</span> Death Card Tiebreakers</div>
      <div class="tb-a-grid">${sessions.map(renderTiebreakCard).join('')}</div>
    `;
    el.querySelectorAll('[data-tb-act]').forEach(btn => {
      btn.addEventListener('click', async () => {
        if (tiebreakBusy) return;
        const act = btn.dataset.tbAct;
        const id = btn.dataset.tbId;
        if (act === 'start' && !confirm('Start the Death Card tiebreaker for this room?\n\nTied teams will see the cards on their devices and each round lasts 20 seconds.')) return;
        if (act === 'reset' && !confirm('Reset this tiebreaker?\n\nAll rounds are wiped and the tied teams start again from round 1.')) return;
        if (act === 'advance' && btn.textContent.includes('Reveal') && !confirm('Reveal now?\n\nTeams that have not picked get a random leftover card.')) return;
        tiebreakBusy = true;
        btn.disabled = true;
        try {
          if (act === 'start') await api.admin.tiebreakStart(id);
          else if (act === 'advance') await api.admin.tiebreakAdvance(id);
          else if (act === 'reset') await api.admin.tiebreakReset(id);
          lastTiebreakJson = '';
          await refreshTiebreaks();
        } catch (err) {
          toast(err.message, { error: true });
        } finally {
          tiebreakBusy = false;
        }
      });
    });
  }

  async function refreshTiebreaks() {
    if (!roundData?.round_id || !root.isConnected) return;
    try {
      const sessions = await api.admin.tiebreaks(roundData.round_id);
      const json = JSON.stringify(sessions);
      // Always redraw while a round is counting down (the timer text changes);
      // otherwise only when something changed, so buttons aren't yanked mid-click.
      const counting = sessions.some(s => s.status === 'ACTIVE' && s.current_round && !s.current_round.is_resolved);
      if (json !== lastTiebreakJson || counting || !body.querySelector('#tiebreak-section')?.innerHTML) {
        lastTiebreakJson = json;
        renderTiebreakSection(sessions);
      }
    } catch (_) {}
  }

  // Delivery board for "Publish Final Results to All Teams". One room card per
  // room; one chip per team. Before publishing a chip is a presence dot (blue =
  // device connected and ready). After publishing it becomes a delivery ring:
  // sending → received (the device acknowledged THIS broadcast and echoed the
  // outcome it displayed, which is checked against the server's result).
  // Publishing again re-sends to everyone and resets every ring.
  async function openPublishFinalResultsModal(roundId, detail, allGamesCompleted) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal broadcast-modal">
        <div class="bl-bm-header">
          <div class="bl-bm-header-content">
            <div class="bl-bm-header-left">
              <div class="bl-bm-radar-icon"><span class="mi">sensors</span></div>
              <div>
                <div class="bl-bm-title">Publish Final Results to All Teams</div>
                <div class="bl-bm-subtitle">全チームに結果公開 · every device receives its own Round 2 outcome and confirms it</div>
              </div>
            </div>
            <span class="pill" id="bm-status-pill">● LOADING…</span>
          </div>
        </div>

        <div class="bl-bm-body" id="bm-body">
          <div class="spinner" style="margin: 60px auto;"></div>
        </div>

        <div class="bl-bm-footer">
          <div class="bm-legend" id="bm-legend"></div>
          <div class="bm-footer-actions">
            <button type="button" class="btn" id="bm-close-btn">Close</button>
            <button type="button" class="btn success solid" id="bm-publish-btn">
              <span class="mi">campaign</span> <span id="bm-publish-label">Publish Results</span>
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(backdrop);

    let board = null;          // last /team-connections response
    let isBroadcasting = false;
    let poll = null;

    function closeModal() {
      if (poll) clearInterval(poll);
      poll = null;
      backdrop.remove();
    }
    backdrop.querySelector('#bm-close-btn').onclick = closeModal;
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });

    const OUTCOME_LABEL = { QUALIFIED: 'Qualified', ELIMINATED: 'Eliminated', TIEBREAK: 'Tiebreak' };

    // Ring is an SVG circle (r=15 → circumference ≈ 94). `fill` is 0..1.
    function ring(state, fill, icon) {
      const circ = 94;
      return `
        <span class="bm-ring ${state}">
          <svg viewBox="0 0 36 36" aria-hidden="true">
            <circle class="bm-ring-bg" cx="18" cy="18" r="15"></circle>
            <circle class="bm-ring-fg" cx="18" cy="18" r="15"
              stroke-dasharray="${circ}" stroke-dashoffset="${Math.round(circ * (1 - fill))}"></circle>
          </svg>
          <span class="bm-ring-icon">${icon}</span>
        </span>`;
    }

    function chipState(t, isPublished) {
      if (!isPublished) {
        return t.is_connected
          ? { cls: 'ready',   ring: ring('ready', 0, '<span class="bm-dot blue"></span>'),  text: 'Connected' }
          : { cls: 'offline', ring: ring('offline', 0, '<span class="bm-dot gray"></span>'), text: 'Offline' };
      }
      // Held for a Death Card tiebreak: the device shows the tiebreak screen
      // and acks 'TIEBREAK'; its real outcome arrives when the draw resolves.
      if (t.expected_outcome === 'TIEBREAK') {
        if (t.is_acknowledged) return { cls: 'tiebreak', ring: ring('tiebreak', 1, '<span class="mi">style</span>'), text: 'In tiebreak' };
        if (t.is_connected) return { cls: 'sending', ring: ring('sending', 0.6, '<span class="mi spin">sync</span>'), text: 'Sending…' };
        return { cls: 'pending', ring: ring('pending', 0.25, '<span class="bm-dot gray"></span>'), text: 'Offline' };
      }
      // Tiebreak just resolved: the old 'TIEBREAK' ack is stale, not wrong.
      if (t.is_acknowledged && !t.is_verified && t.acked_outcome === 'TIEBREAK') {
        return { cls: 'sending', ring: ring('sending', 0.6, '<span class="mi spin">sync</span>'), text: 'Sending…' };
      }
      if (t.is_acknowledged && !t.is_verified) {
        return { cls: 'mismatch', ring: ring('mismatch', 1, '<span class="mi">priority_high</span>'),
                 text: `Showed ${OUTCOME_LABEL[t.acked_outcome] || t.acked_outcome || '?'} — expected ${OUTCOME_LABEL[t.expected_outcome] || '?'}` };
      }
      if (t.is_acknowledged) {
        // The green ring already says "received"; the label is the outcome the device showed.
        return { cls: 'confirmed', ring: ring('confirmed', 1, '<span class="mi">check</span>'),
                 text: OUTCOME_LABEL[t.expected_outcome] || 'Received' };
      }
      if (t.is_connected) {
        return { cls: 'sending', ring: ring('sending', 0.6, '<span class="mi spin">sync</span>'), text: 'Sending…' };
      }
      // Offline devices get the result from the 3s poll as soon as they come back.
      return { cls: 'pending', ring: ring('pending', 0.25, '<span class="bm-dot gray"></span>'), text: 'Offline' };
    }

    function renderTeamChip(t, isPublished) {
      const st = chipState(t, isPublished);
      const ackTime = t.acknowledged_at ? new Date(t.acknowledged_at).toLocaleTimeString() : '';
      const title = `${t.team_name || t.team_code}${ackTime ? ` · confirmed ${ackTime}` : ''}`;
      return `
        <div class="bm-team ${st.cls}" title="${title.replace(/"/g, '&quot;')}">
          ${st.ring}
          <span class="bm-team-code">${t.team_code}</span>
          <span class="bm-team-status">${st.text}</span>
        </div>`;
    }

    function renderBoard() {
      const body = backdrop.querySelector('#bm-body');
      const pill = backdrop.querySelector('#bm-status-pill');
      const publishBtn = backdrop.querySelector('#bm-publish-btn');
      const publishLabel = backdrop.querySelector('#bm-publish-label');
      const legend = backdrop.querySelector('#bm-legend');
      if (!body || !board) return;

      const isPublished = !!board.is_published;
      const total = board.total_teams || 0;

      if (pill) {
        if (isBroadcasting) {
          pill.className = 'pill IN_PROGRESS';
          pill.textContent = '● SENDING…';
        } else if (isPublished) {
          const allIn = total > 0 && board.acknowledged_count >= total;
          pill.className = `pill ${allIn ? 'COMPLETED' : 'ACTIVE'}`;
          const at = board.results_published_at ? new Date(board.results_published_at).toLocaleTimeString() : '';
          pill.textContent = `● ${board.acknowledged_count}/${total} RECEIVED${at ? ` · SENT ${at}` : ''}`;
        } else {
          pill.className = 'pill NOT_STARTED';
          pill.textContent = `● ${board.connected_count}/${total} CONNECTED · NOT SENT YET`;
        }
      }

      if (publishBtn) {
        publishBtn.disabled = isBroadcasting;
        publishLabel.textContent = isBroadcasting
          ? 'Sending…'
          : isPublished ? 'Send Results Again' : 'Publish Results';
      }

      if (legend) {
        const anyTiebreak = (board.rooms || []).some(r => r.teams.some(t => t.expected_outcome === 'TIEBREAK'));
        legend.innerHTML = isPublished
          ? `<span><span class="bm-dot green"></span> Received</span>
             <span><span class="bm-dot amber"></span> Sending</span>
             ${anyTiebreak ? '<span><span class="bm-dot purple"></span> In tiebreak</span>' : ''}
             <span><span class="bm-dot gray"></span> Offline</span>`
          : `<span><span class="bm-dot blue"></span> Connected &amp; ready</span>
             <span><span class="bm-dot gray"></span> Offline</span>`;
      }

      const rooms = board.rooms || [];
      const unassigned = board.unassigned_teams || [];
      body.innerHTML = `
        <div class="bm-rooms">
          ${rooms.length === 0 ? `
            <div class="bm-empty"><span class="mi">meeting_room</span> No rooms in this round yet.</div>
          ` : rooms.map(room => `
            <div class="bm-room">
              <div class="bm-room-head">
                <span class="bm-room-code"><span class="mi">meeting_room</span> ${room.room_code}</span>
                <span class="bm-room-count">
                  ${isPublished
                    ? `${room.acknowledged_count}/${room.team_count} received`
                    : `${room.connected_count}/${room.team_count} connected`}
                </span>
              </div>
              <div class="bm-team-grid">
                ${room.teams.length
                  ? room.teams.map(t => renderTeamChip(t, isPublished)).join('')
                  : '<div class="bm-room-empty">No teams seated in this room</div>'}
              </div>
            </div>
          `).join('')}
        </div>
        ${unassigned.length ? `
          <div class="bm-unassigned">
            <span class="mi">person_off</span>
            ${unassigned.length} team${unassigned.length === 1 ? '' : 's'} not seated in any room won't receive results:
            ${unassigned.map(t => t.team_code).join(', ')}
          </div>` : ''}
      `;
    }

    async function refresh() {
      try {
        board = await api.admin.getTeamConnections(roundId);
        renderBoard();
      } catch (err) {
        const body = backdrop.querySelector('#bm-body');
        if (body && !board) body.innerHTML = `<p class="status-note error" style="padding:16px;">${err.message}</p>`;
      }
    }

    async function publish() {
      if (isBroadcasting) return;
      const msg = board?.is_published
        ? 'Send the final results to all team devices again?\n\nEvery device will replay its outcome (VISA Extended / Sky Laser) and confirm receipt again.'
        : allGamesCompleted
          ? 'Publish final results and Round 2 qualifications to all team devices now?'
          : '⚠️ Some games or sub-rounds are not finished yet.\n\nPublishing will close them, compute the final results, and send every team its Round 2 outcome.\n\nProceed?';
      if (!confirm(msg)) return;

      isBroadcasting = true;
      renderBoard();
      try {
        await api.admin.publishRoundLeaderboard(roundId);
        toast(board?.is_published ? '📡 Results re-sent to all team devices.' : '🎉 Final results published to all team devices!');
        await refresh();
        load();
      } catch (err) {
        toast(err.message, { error: true });
      } finally {
        isBroadcasting = false;
        renderBoard();
      }
    }

    backdrop.querySelector('#bm-publish-btn').addEventListener('click', publish);

    await refresh();
    poll = setInterval(refresh, 2000);
  }

  function openDemoStartModal(code, roundId) {
    // MindMaze, Ace of Spades, and King of Diamonds all run fixed-length
    // auto-submit sub-rounds (settings.mindmaze_round_seconds /
    // ace_spade_round_seconds / king_diamond_round_seconds), exactly as
    // they do for real — there is no duration to pick.
    const hasFixedTiming = code === 'MINDMAZE' || code === 'ACE_SPADE' || code === 'KING_DIAMOND';
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3><span class="mi">school</span> Start ${GAMES[code]?.en || code} Demo</h3>
        <p style="font-size:0.8rem; color:var(--bl-gray); margin-bottom:12px;">
          Arms a practice round in every room in this round. Teams play on the real game screens
          behind a "practice" banner; nothing they score is saved. Use <strong>Practice Again</strong>
          to deal a fresh attempt, and <strong>End Demo</strong> to hand the screens back.
        </p>
        <form id="demo-start-form">
          ${hasFixedTiming ? `
            <p style="font-size:0.78rem; color:var(--bl-gray); margin-bottom:12px;">
              ${GAMES[code]?.en || code} uses its normal fixed sub-round length with auto-submit, so there is no duration to configure.
            </p>
          ` : `
            <div class="field"><label class="tier-label"><span class="primary">Duration (minutes)</span><span class="secondary">per sub-round, 1&ndash;60</span></label><input name="duration" type="number" min="1" max="60" value="1" /></div>
          `}
          <div class="field"><label class="tier-label"><span class="primary">Demo sub-rounds</span><span class="secondary">1&ndash;5, default 1</span></label><input name="rounds" type="number" min="1" max="5" value="1" /></div>
          <div class="btn-row">
            <button type="submit" class="btn primary">Start demo in all rooms</button>
            <button type="button" class="btn" id="demo-cancel">Cancel</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#demo-cancel').addEventListener('click', () => backdrop.remove());
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) backdrop.remove(); });
    backdrop.querySelector('#demo-start-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const duration = hasFixedTiming ? 1 : Number(fd.get('duration'));
      try {
        const res = await api.admin.demo.start(roundId, code, duration, Number(fd.get('rounds')));
        backdrop.remove();
        if (res.failed.length) {
          toast(`Demo started in ${res.succeeded.length} rooms, ${res.failed.length} failed: ${res.failed[0].reason}`, { error: true });
        } else {
          toast(`Demo started in ${res.succeeded.length} rooms!`);
        }
        load();
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  // Helper: render an SVG circular progress ring
  function svgRing(size, stroke, pct, color, label, subLabel) {
    const r = (size - stroke) / 2;
    const circ = 2 * Math.PI * r;
    const offset = circ - (pct / 100) * circ;
    const pctSize = size <= 52 ? '0.6rem' : '0.72rem';
    const subSize = size <= 52 ? '0.45rem' : '0.52rem';
    return `
      <div class="ring-wrap" style="width:${size}px; height:${size}px;">
        <svg width="${size}" height="${size}">
          <circle class="ring-bg" cx="${size/2}" cy="${size/2}" r="${r}" stroke-width="${stroke}"/>
          <circle class="ring-fg" cx="${size/2}" cy="${size/2}" r="${r}" stroke-width="${stroke}"
            stroke="${color}" stroke-dasharray="${circ}" stroke-dashoffset="${offset}"/>
        </svg>
        <div class="ring-label">
          <span class="ring-pct" style="font-size:${pctSize};">${label}</span>
          ${subLabel ? `<span class="ring-sub" style="font-size:${subSize};">${subLabel}</span>` : ''}
        </div>
      </div>
    `;
  }

  function openResultsModal(code, roundId, initialSessions) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    let modalPoll = null;
    let lastRenderedJson = '';

    backdrop.innerHTML = `
      <div class="modal progress-modal">
        <!-- Header -->
        <div class="pm-header">
          <div class="pm-header-left">
            <h3>
              <span class="mi" style="color:var(--bl-red);">monitoring</span>
              ${GAMES[code]?.en || code} — Live Progress
              <span id="modal-header-badge" class="pill IN_PROGRESS" style="font-size:0.65rem;">LIVE</span>
            </h3>
            <div class="pm-subtitle">All rooms at a glance · auto-refreshing every 1.5s</div>
          </div>
          <div style="display:flex; align-items:center; gap:5px; font-size:0.7rem; font-weight:700; color:#059669; background:#ecfdf5; border:1px solid #a7f3d0; padding:3px 8px; border-radius:4px;">
            <span class="status-dot green pulse"></span> Live
          </div>
        </div>

        <!-- Summary Rings -->
        <div class="pm-summary" id="modal-summary-rings"></div>

        <!-- Room Grid -->
        <div class="pm-room-grid" id="modal-rooms-grid"></div>

        <!-- Expanded Detail Panel (hidden by default) -->
        <div id="modal-detail-panel" style="display:none; border-top:1px solid #edf0f2; margin-top:10px; padding-top:10px; max-height:35vh; overflow-y:auto;"></div>

        <!-- Footer -->
        <div class="pm-footer">
          <button type="button" class="btn success solid" id="publish-results-modal-btn">
            <span class="mi">cast</span> Publish Results
          </button>
          <div style="display:flex; gap:8px;">
            <button type="button" class="btn danger" id="force-complete-btn">
              <span class="mi">flag</span> Force Complete
            </button>
            <button type="button" class="btn primary" id="close-results">Close</button>
          </div>
        </div>
      </div>
    `;

    // Track which room detail is expanded
    let expandedRoomId = null;

    function renderModalContent(gameSessions) {
      const sessList = gameSessions.filter(s => s.game_code === code || s.session?.game_code === code);
      const isJackHeart = code === 'JACK_HEART';

      const currentJson = JSON.stringify(sessList);
      if (currentJson === lastRenderedJson) return;
      lastRenderedJson = currentJson;

      // Aggregate global statistics
      let totalSubroundsAllRooms = 0;
      let closedSubroundsAllRooms = 0;
      let totalActiveTeamsAllRooms = 0;
      let totalSubmittedAllRooms = 0;
      let publishedViewsAllRooms = 0;

      sessList.forEach(s => {
        const sessionObj = s.session || s;
        const rounds = s.rounds || s.session?.rounds || [];
        const activeRoomTeams = sessionObj.total_room_teams > 0 ? sessionObj.total_room_teams : Math.max(1, (rounds[0]?.submitted_teams?.length || 1));
        totalActiveTeamsAllRooms += activeRoomTeams;
        totalSubroundsAllRooms += rounds.length;
        closedSubroundsAllRooms += rounds.filter(r => r.is_closed).length;

        // Count current active subround submissions
        const activeRound = rounds.find(r => r.start_time && !r.is_closed && !(r.deadline && new Date(r.deadline) <= new Date()));
        if (activeRound) {
          const sd = activeRound.submission_details || [];
          totalSubmittedAllRooms += sd.length > 0 ? sd.length : ((activeRound.submitted_teams?.length) || 0);
        }

        const pViewed = sessionObj.published_viewed_teams || [];
        publishedViewsAllRooms += pViewed.length;
      });

      const subroundsPct = totalSubroundsAllRooms > 0 ? Math.round((closedSubroundsAllRooms / totalSubroundsAllRooms) * 100) : 0;
      const submitPctGlobal = totalActiveTeamsAllRooms > 0 ? Math.min(100, Math.round((totalSubmittedAllRooms / totalActiveTeamsAllRooms) * 100)) : 0;
      const publishedPct = totalActiveTeamsAllRooms > 0 ? Math.min(100, Math.round((publishedViewsAllRooms / totalActiveTeamsAllRooms) * 100)) : 0;
      const isGamePublished = sessList.some(s => (s.session || s).is_published);

      // Update Header Badge
      const headerBadge = backdrop.querySelector('#modal-header-badge');
      if (headerBadge) {
        headerBadge.className = `pill ${isGamePublished ? 'COMPLETED' : 'IN_PROGRESS'}`;
        headerBadge.textContent = isGamePublished ? 'PUBLISHED' : 'LIVE';
      }

      // Render summary rings
      const summaryEl = backdrop.querySelector('#modal-summary-rings');
      if (summaryEl) {
        const roundsColor = subroundsPct === 100 ? '#059669' : '#2563eb';
        const submitColor = submitPctGlobal === 100 ? '#059669' : (submitPctGlobal > 0 ? '#3b82f6' : '#adb5bd');
        const viewColor = publishedPct === 100 ? '#059669' : (publishedPct > 0 ? '#d97706' : '#adb5bd');
        summaryEl.innerHTML = `
          <div class="pm-summary-stat">
            ${svgRing(64, 5, subroundsPct, roundsColor, `${subroundsPct}%`, '')}
            <span class="pm-stat-label">Rounds ${closedSubroundsAllRooms}/${totalSubroundsAllRooms}</span>
          </div>
          <div class="pm-summary-stat">
            ${svgRing(64, 5, submitPctGlobal, submitColor, `${submitPctGlobal}%`, '')}
            <span class="pm-stat-label">Submitted ${totalSubmittedAllRooms}/${totalActiveTeamsAllRooms}</span>
          </div>
          <div class="pm-summary-stat">
            ${svgRing(64, 5, publishedPct, viewColor, `${publishedPct}%`, '')}
            <span class="pm-stat-label">Viewed ${publishedViewsAllRooms}/${totalActiveTeamsAllRooms}</span>
          </div>
          <div class="pm-summary-stat">
            <div style="display:flex; flex-direction:column; align-items:center; gap:4px;">
              <span style="font-size:1.6rem; font-weight:800; color:#212529;">${sessList.length}</span>
            </div>
            <span class="pm-stat-label">Rooms</span>
          </div>
        `;
      }

      // Render room grid
      const gridEl = backdrop.querySelector('#modal-rooms-grid');
      if (!gridEl) return;

      if (sessList.length === 0) {
        gridEl.innerHTML = `<div class="subround-empty" style="grid-column:1/-1;">No active sessions for ${GAMES[code]?.en || code}.</div>`;
        return;
      }

      gridEl.innerHTML = sessList.map(s => {
        const sessionObj = s.session || s;
        const rounds = s.rounds || s.session?.rounds || [];
        const roomActiveTeams = sessionObj.total_room_teams > 0 ? sessionObj.total_room_teams : Math.max(1, (rounds[0]?.submitted_teams?.length || 1));
        const roomClosedCount = rounds.filter(r => r.is_closed).length;
        const roomProgressPct = rounds.length > 0 ? Math.round((roomClosedCount / rounds.length) * 100) : 0;
        const roomPublishedViewed = sessionObj.published_viewed_teams || [];
        const roomPublishedPct = roomActiveTeams > 0 ? Math.min(100, Math.round((roomPublishedViewed.length / roomActiveTeams) * 100)) : 0;

        // Current active subround submission progress
        const activeRound = rounds.find(r => r.start_time && !r.is_closed && !(r.deadline && new Date(r.deadline) <= new Date()));
        let submitPct = 0;
        let submitCount = 0;
        if (activeRound) {
          const sd = activeRound.submission_details || [];
          submitCount = sd.length > 0 ? sd.length : ((activeRound.submitted_teams?.length) || 0);
          submitPct = roomActiveTeams > 0 ? Math.min(100, Math.round((submitCount / roomActiveTeams) * 100)) : 0;
        }

        const progressColor = roomProgressPct === 100 ? '#059669' : '#3b82f6';
        const submitRingColor = submitPct === 100 ? '#059669' : (submitPct > 0 ? '#2563eb' : '#adb5bd');

        // Sub-round dots
        const srDotsHtml = rounds.map(r => {
          const isClosed = r.is_closed || (r.deadline && new Date(r.deadline) <= new Date());
          const isActive = r.start_time && !isClosed;
          const cls = isClosed ? 'done' : isActive ? 'active' : 'pending';
          return `<span class="pm-sr-dot ${cls}" title="SR${r.round_number}">${r.round_number}</span>`;
        }).join('');

        const roomId = sessionObj.session_id || sessionObj.room_id || '';
        const isExpanded = expandedRoomId === roomId;

        // Published bar
        const publishedHtml = sessionObj.is_published ? `
          <div class="pm-published-bar">
            <span class="mi" style="font-size:13px;">verified</span>
            Published · ${roomPublishedViewed.length}/${roomActiveTeams} viewed
          </div>
        ` : '';

        return `
          <div class="pm-room-card" data-room-id="${roomId}">
            <div class="pm-room-header">
              <div>
                <div class="pm-room-name">Room ${sessionObj.room_code || sessionObj.room_id?.slice(0, 8) || '—'}</div>
                <div class="pm-room-meta">${roomActiveTeams} teams · <span class="pill ${sessionObj.status}" style="font-size:0.55rem; padding:1px 5px;">${sessionObj.status}</span></div>
              </div>
            </div>
            <div class="pm-rings">
              ${svgRing(50, 4, roomProgressPct, progressColor, `${roomClosedCount}/${rounds.length}`, 'rounds')}
              ${activeRound ? svgRing(50, 4, submitPct, submitRingColor, `${submitCount}/${roomActiveTeams}`, 'submit') : svgRing(50, 4, roomProgressPct === 100 ? 100 : 0, roomProgressPct === 100 ? '#059669' : '#adb5bd', roomProgressPct === 100 ? '✓' : '—', 'submit')}
            </div>
            <div class="pm-sr-dots">${srDotsHtml}</div>
            ${publishedHtml}
            <button class="pm-expand-btn" data-expand-room="${roomId}">
              <span class="mi" style="font-size:13px;">${isExpanded ? 'expand_less' : 'expand_more'}</span>
              ${isExpanded ? 'Collapse' : 'Details'}
            </button>
          </div>
        `;
      }).join('');

      // Wire expand buttons
      gridEl.querySelectorAll('[data-expand-room]').forEach(btn => {
        btn.addEventListener('click', () => {
          const rid = btn.dataset.expandRoom;
          if (expandedRoomId === rid) {
            expandedRoomId = null;
          } else {
            expandedRoomId = rid;
          }
          renderDetailPanel(sessList);
          // Force re-render to update button states
          lastRenderedJson = '';
          renderModalContent(gameSessions);
        });
      });

      renderDetailPanel(sessList);
    }

    function renderDetailPanel(sessList) {
      const panel = backdrop.querySelector('#modal-detail-panel');
      if (!panel) return;

      if (!expandedRoomId) {
        panel.style.display = 'none';
        panel.innerHTML = '';
        return;
      }

      const s = sessList.find(s => {
        const so = s.session || s;
        return (so.session_id || so.room_id) === expandedRoomId;
      });
      if (!s) { panel.style.display = 'none'; return; }

      panel.style.display = 'block';
      const sessionObj = s.session || s;
      const rounds = s.rounds || s.session?.rounds || [];
      const roomActiveTeams = sessionObj.total_room_teams > 0 ? sessionObj.total_room_teams : Math.max(1, (rounds[0]?.submitted_teams?.length || 1));
      const roomPublishedViewed = sessionObj.published_viewed_teams || [];
      const activeTeamCodes = sessionObj.active_team_codes || [];
      const pendingViewTeams = activeTeamCodes.filter(t => !roomPublishedViewed.includes(t));
      const isJackHeart = code === 'JACK_HEART';

      panel.innerHTML = `
        <div style="font-weight:800; font-size:0.88rem; color:#212529; margin-bottom:8px; display:flex; align-items:center; gap:6px;">
          <span class="mi" style="font-size:16px;">meeting_room</span>
          Room ${sessionObj.room_code || sessionObj.room_id?.slice(0, 8) || '—'} — Detail View
        </div>
        ${sessionObj.is_published && (roomPublishedViewed.length > 0 || pendingViewTeams.length > 0) ? `
          <div style="background:#ecfdf5; border:1px solid #a7f3d0; border-radius:6px; padding:6px 10px; margin-bottom:8px; font-size:0.68rem;">
            ${roomPublishedViewed.length > 0 ? `<div style="color:#047857; font-weight:600; margin-bottom:2px;">✓ Viewed: ${roomPublishedViewed.map(t => `<span style="background:#fff; border:1px solid #a7f3d0; padding:1px 4px; border-radius:3px; margin-right:2px; font-weight:700;">${t}</span>`).join('')}</div>` : ''}
            ${pendingViewTeams.length > 0 ? `<div style="color:#b45309; font-weight:600;">⏳ Awaiting: ${pendingViewTeams.map(t => `<span style="background:#fffbeb; border:1px solid #fde68a; padding:1px 4px; border-radius:3px; margin-right:2px; font-weight:700;">${t}</span>`).join('')}</div>` : ''}
          </div>
        ` : ''}
        ${rounds.map(r => {
          const subDetails = r.submission_details || [];
          const submittedCount = subDetails.length > 0 ? subDetails.length : ((r.submitted_teams?.length) || 0);
          const isClosed = Boolean(r.is_closed || (r.deadline && new Date(r.deadline) <= new Date()));
          const submitPct = roomActiveTeams > 0 ? Math.min(100, Math.round((submittedCount / roomActiveTeams) * 100)) : 0;
          const dotColor = isClosed ? 'blue' : (r.start_time ? 'green' : 'gray');
          const statusText = isClosed ? 'Closed' : (r.start_time ? 'Active' : 'Pending');
          const viewedTeams = r.viewed_teams || [];
          const viewedPct = roomActiveTeams > 0 ? Math.min(100, Math.round((viewedTeams.length / roomActiveTeams) * 100)) : 0;

          return `
            <div style="background:#fff; border:1px solid #edf0f2; border-radius:6px; padding:8px 10px; margin-bottom:6px;">
              <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
                <div style="display:flex; align-items:center; gap:6px; font-size:0.78rem; font-weight:800; color:#212529;">
                  <span class="status-dot ${dotColor}"></span>
                  SR ${r.round_number}
                  <span style="font-weight:600; font-size:0.65rem; color:#868e96;">${statusText}</span>
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                  <span style="font-size:0.68rem; font-weight:700; color:#495057;">Submitted: ${submittedCount}/${roomActiveTeams} (${submitPct}%)</span>
                  ${r.deadline ? `<span style="font-size:0.65rem; color:#868e96;">⏰ ${new Date(r.deadline).toLocaleTimeString()}</span>` : ''}
                </div>
              </div>
              ${isJackHeart && r.round_number >= 2 ? `
                <div style="font-size:0.65rem; color:#6c757d; margin-bottom:3px;">Standings viewed: ${viewedTeams.length}/${roomActiveTeams} (${viewedPct}%)</div>
              ` : ''}
              ${subDetails.length > 0 ? `
                <div style="display:flex; flex-wrap:wrap; gap:3px; margin-top:4px;">
                  ${subDetails.map(sd => `
                    <span style="font-size:0.62rem; background:#f1f3f5; padding:2px 6px; border-radius:3px; font-weight:600; color:#495057;">
                      ${sd.team_code} ${sd.detail || (sd.score !== null ? `+${sd.score}` : '✓')}
                    </span>
                  `).join('')}
                </div>
              ` : (r.start_time ? `<div style="font-size:0.62rem; color:#adb5bd; font-style:italic;">Awaiting submissions...</div>` : '')}
            </div>
          `;
        }).join('')}
      `;
    }

    function closeModal() {
      if (modalPoll) {
        clearInterval(modalPoll);
        modalPoll = null;
      }
      backdrop.remove();
    }

    // Attach static footer listeners once
    backdrop.querySelector('#close-results').onclick = closeModal;
    backdrop.querySelector('#publish-results-modal-btn').onclick = (e) => {
      const pBtn = e.currentTarget;
      pBtn.disabled = true;
      const originalHtml = pBtn.innerHTML;
      pBtn.innerHTML = '<span class="mi spin">autorenew</span> Publishing...';
      api.admin.publishGameForRound(roundId, code)
        .then(() => {
          toast(`Published ${GAMES[code]?.en || code} results to all teams in all rooms!`);
          load();
        })
        .catch(err => {
          toast(err.message, { error: true });
          pBtn.disabled = false;
          pBtn.innerHTML = originalHtml;
        });
    };
    backdrop.querySelector('#force-complete-btn').onclick = (e) => {
      const fcBtn = e.currentTarget;
      fcBtn.disabled = true;
      const originalHtml = fcBtn.innerHTML;
      fcBtn.innerHTML = '<span class="mi spin">autorenew</span> Completing...';
      api.admin.forceCompleteSessionsForRound(roundId, code)
        .then(res => {
          toast(`Completed in ${res.succeeded.length} rooms`);
          load();
        })
        .catch(err => {
          toast(err.message, { error: true });
          fcBtn.disabled = false;
          fcBtn.innerHTML = originalHtml;
        });
    };

    document.body.appendChild(backdrop);
    renderModalContent(initialSessions);

    // Live auto-refresh polling every 1.5 seconds
    modalPoll = setInterval(async () => {
      if (!backdrop.isConnected) {
        clearInterval(modalPoll);
        return;
      }
      try {
        const updatedSessions = await api.admin.getRoundGameSessions(roundId);
        renderModalContent(updatedSessions);
      } catch (_) { }
    }, 1500);

    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });
  }





  function openStartModal(code, roundId) {
    const isMindmaze = code === 'MINDMAZE';
    const isAceSpade = code === 'ACE_SPADE';
    // Aug 2026: King of Diamonds joins MindMaze in running a fixed-length,
    // auto-submit sub-round (see session_service.start_session /
    // settings.king_diamond_round_seconds) — the admin no longer picks a
    // duration for it either.
    const isKingDiamond = code === 'KING_DIAMOND';
    const hasFixedTiming = isMindmaze || isAceSpade || isKingDiamond;
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3>Start ${GAMES[code]?.en || code} — All Rooms</h3>
        <form id="start-round-form">
          ${isMindmaze ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              MindMaze plays 30s memorize + 30s input per sub-round. Sub-round 1 starts with a 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : isAceSpade ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              Ace of Spades plays 30s memorize + 40s card recall per sub-round, each preceded by a short shuffle-and-deal animation. Sub-round 1 starts with a 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : isKingDiamond ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              King of Diamonds runs a fixed 45s sub-round: teams pick a number, then it auto-submits — no submit button. Sub-round 1 starts with a 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : `

            <div class="field">
              <label class="tier-label"><span class="primary">Duration per round (minutes)</span><span class="secondary">How long each game round lasts</span></label>
              <input name="duration" type="number" min="1" max="60" value="1" />
            </div>
          `}
          <div class="field">
            <label class="tier-label"><span class="primary">${hasFixedTiming ? 'Number of sub-rounds' : 'Number of game rounds'}</span><span class="secondary">Configure how many rounds to run (1 to 10)</span></label>
            <input name="rounds" type="number" min="1" max="10" value="5" />
          </div>
          <div class="btn-row">
            <button type="submit" class="btn primary"><span class="mi">rocket_launch</span> Start in all rooms</button>
            <button type="button" class="btn" id="cancel">Cancel</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#cancel').addEventListener('click', () => backdrop.remove());
    backdrop.querySelector('#start-round-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      // duration_minutes is ignored server-side for MINDMAZE and
      // KING_DIAMOND (see session_service.start_session) — send a
      // harmless placeholder so the request still satisfies the schema's
      // ge=1 bound.
      const duration = hasFixedTiming ? 1 : Number(fd.get('duration'));
      try {
        const res = await api.admin.startSessionForRound(roundId, code, duration, Number(fd.get('rounds')));
        backdrop.remove();
        toast(`Started in ${res.succeeded.length} rooms!`);
        load();
      } catch (err) { toast(err.message, { error: true }); }
    });
  }



  load().then(refreshTiebreaks);
  pollInterval = setInterval(() => {
    if (!root.isConnected) {
      clearInterval(pollInterval);
      return;
    }
    if (document.querySelector('.modal-backdrop')) return;
    load(true);
  }, 2500);
  tiebreakPoll = setInterval(() => {
    if (!root.isConnected) { clearInterval(tiebreakPoll); return; }
    refreshTiebreaks();
  }, 1500);

  return () => {
    if (pollInterval) clearInterval(pollInterval);
    if (tiebreakPoll) clearInterval(tiebreakPoll);
  };
}
