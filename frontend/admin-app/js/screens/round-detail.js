import { api } from '../../../shared/js/api.js';
import { openWinnersModal } from './winners-export.js';
import { GAMES } from '../../../shared/js/copy.js';
import { toast } from '../../../shared/js/ui.js';

const NEXT_STATUS = { NOT_STARTED: 'ACTIVE', ACTIVE: 'COMPLETED' };
const ALL_GAMES = ['MINDMAZE', 'ACE_SPADE', 'KING_DIAMOND', 'JACK_HEART'];

export function renderRoundDetail(root, navigate, roundId) {
  let pollInterval = null;
  let roundData = null;  // fix: was undeclared (implicit global / strict-mode error)

  root.innerHTML = `
    <p class="admin-crumb"><a href="#/rounds">← Rounds</a></p>
    <div id="detail-body"><div class="spinner"></div></div>
  `;
  const body = root.querySelector('#detail-body');

  async function load(silent = false) {
    if (!silent) {
      body.innerHTML = `<div class="spinner"></div>`;
    }
    try {
      const [detail, lineup, gameSessions, demoSessions] = await Promise.all([
        api.admin.getRound(roundId),
        api.admin.gameLineup(roundId).catch(() => []),
        api.admin.getRoundGameSessions(roundId).catch(() => []),
        api.admin.demo.list(roundId).catch(() => []),
      ]);
      roundData = detail;
      if (!silent) {
        render(detail, lineup, gameSessions, demoSessions);
      } else {
        const simArea = body.querySelector('#simultaneous-area');
        if (simArea) renderSimultaneousControls(simArea, lineup, gameSessions, demoSessions);
      }
    } catch (err) {
      if (!silent) {
        body.innerHTML = `<p class="status-note error">${err.message}</p>`;
      }
    }
  }

  function render(detail, lineup, gameSessions = [], demoSessions = []) {

    const next = NEXT_STATUS[detail.status];
    body.innerHTML = `
      <div class="admin-topline">
        <h1 class="admin-h1">${detail.name} <span style="color:var(--bl-gray);font-weight:400;">#${detail.round_number}</span></h1>
        <div class="btn-row">
          <span class="pill ${detail.status}">${detail.status?.replace('_',' ')}</span>
          <button id="export-winners-btn" class="btn" title="Round 2 qualifier list as an .xlsx you can forward">
            <span class="mi">download</span> Export Qualifiers
          </button>
          ${next ? `<button id="advance-btn" class="btn primary">Advance → ${next.replace('_',' ')}</button>` : ''}
        </div>
      </div>

      <h3 style="margin-bottom:8px;"><span class="mi">bolt</span> Simultaneous Game Control (All Rooms)</h3>
      <div id="simultaneous-area" style="margin-bottom:var(--gap-lg);"></div>

      <h3 style="margin-bottom:8px;">Game lineup</h3>
      <div id="lineup-area"></div>

      <h3 style="margin:var(--gap-lg) 0 8px;">Qualification Rule</h3>
      <div id="qual-area"></div>

      <h3 style="margin:var(--gap-lg) 0 8px;">Rooms</h3>
      <div id="rooms-area"></div>
    `;

    // The qualification rule below decides who ends up in this list, so the
    // two live on the same screen on purpose.
    body.querySelector('#export-winners-btn').addEventListener('click', () => {
      openWinnersModal(roundId, `Round ${detail.round_number} — ${detail.name}`);
    });

    if (next) {
      body.querySelector('#advance-btn').addEventListener('click', async () => {
        if (!confirm(`Advance round to ${next}? This cannot be undone step-by-step.`)) return;
        try {
          await api.admin.setRoundStatus(roundId, next);
          toast('Round status updated');
          load();
        } catch (err) { toast(err.message, { error: true }); }
      });
    }

    renderSimultaneousControls(body.querySelector('#simultaneous-area'), lineup, gameSessions, demoSessions);
    renderLineup(body.querySelector('#lineup-area'), lineup, detail.status);
    renderQualificationRules(body.querySelector('#qual-area'), roundId);
    renderRooms(body.querySelector('#rooms-area'), detail);
  }

  function renderSimultaneousControls(el, lineup, gameSessions = [], demoSessions = []) {
    const activeGames = lineup && lineup.length ? lineup.map((g) => g.game_code) : ALL_GAMES;
    el.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:16px;">
        ${activeGames.map((code) => {
          const sessList = gameSessions.filter((s) => s.game_code === code || s.session?.game_code === code);
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


          return `
            <div class="game-control-card" style="background:#ffffff; border:1px solid #cbd5e1; border-radius:12px; padding:16px; box-shadow:0 1px 3px rgba(0,0,0,0.05);">
              <!-- Game Title Header & Rules -->
              <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #f1f5f9; padding-bottom:10px; margin-bottom:12px;">
                <div>
                  <h3 style="margin:0; font-size:1.2rem; font-weight:700; color:#0f172a;">${GAMES[code]?.en || code}</h3>
                </div>
                <div style="display:flex; gap:8px;">
                  <!-- Bug-fix batch (Aug 2026): this used to be disabled until
                       hasSession, which made it impossible to explain the
                       rules to teams before starting the game clock — the
                       one moment admins actually need it. The backend
                       (show_instructions_for_round) already creates a
                       NOT_STARTED session on demand if none exists yet, so
                       broadcasting rules never required a session to already
                       be running; only this button's disabled state did. -->
                  <button class="btn success" data-act="instructions" data-game="${code}"><span class="mi">campaign</span> Broadcast Rules (5m)</button>
                </div>
              </div>

              <!-- Global Action Buttons -->
              <div style="margin-bottom:16px;">
                <div style="font-size:0.75rem; font-weight:700; color:#64748b; text-transform:uppercase; margin-bottom:8px; letter-spacing:0.05em;">Session Management</div>
                <div class="btn-row" style="flex-wrap:wrap; gap:8px;">
                  <button class="btn primary" data-act="start" data-game="${code}" ${hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">play_circle</span> Start Session</button>
                  <button class="btn" data-act="pause" data-game="${code}" ${!hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">pause</span> Pause All</button>
                  <button class="btn" data-act="resume" data-game="${code}" ${!hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">play_arrow</span> Resume All</button>
                  <button class="btn primary" data-act="show-results" data-game="${code}" ${!hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">bar_chart</span> Show Results</button>
                  <button class="btn success" data-act="publish" data-game="${code}" ${!hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">cast</span> Publish Results to Teams</button>
                  <button class="btn danger solid" data-act="restart" data-game="${code}" ${!hasSession ? 'disabled style="opacity:0.4; cursor:not-allowed;"' : ''}><span class="mi">restart_alt</span> Restart All</button>
                </div>
              </div>

              ${renderDemoPanel(code, demoSessions)}

              <!-- Sub-Round Controls & Status List -->
              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:12px;">
                <div style="font-size:0.8rem; font-weight:700; color:#334155; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center;">
                  <span>Sub-Rounds Status & Controls</span>
                  <span style="font-size:0.75rem; font-weight:500; color:#64748b;">Control sub-rounds individually</span>
                </div>
                
                <div class="subround-grid" style="display:flex; flex-direction:column; gap:8px;">
                  ${subrounds.length > 0 ? subrounds.map((r, idx) => {
                    const isStarted = !!r.start_time;
                    const isClosed = !!r.is_closed || (r.deadline && new Date(r.deadline) <= new Date());

                    const precStarted = idx === 0 ? true : !!(subrounds[idx - 1] && subrounds[idx - 1].start_time);
                    const canStart = precStarted && !isStarted && !isClosed;

                    const badgeHtml = isClosed
                      ? `<span style="background:#fee2e2; color:#991b1b; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">COMPLETED</span>`
                      : isStarted
                      ? `<span style="background:#dcfce7; color:#166534; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">ACTIVE</span>`
                      : `<span style="background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">NOT STARTED</span>`;

                    let actionButtonsHtml = '';
                    if (isClosed) {
                      // Completed sub-round: Hide start button, ONLY show restart button
                      actionButtonsHtml = `
                        <button class="btn danger" style="padding:4px 10px; font-size:0.75rem;" data-act="restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">restart_alt</span> Restart Sub-Round ${r.round_number}</button>
                      `;
                    } else if (isStarted) {
                      // Active sub-round: Only show restart button (pause option removed from sub-rounds)
                      actionButtonsHtml = `
                        <button class="btn danger" style="padding:4px 10px; font-size:0.75rem;" data-act="restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">restart_alt</span> Restart Sub-Round ${r.round_number}</button>
                      `;
                    } else {
                      actionButtonsHtml = `
                        <button class="btn accent" style="padding:4px 10px; font-size:0.75rem; background:var(--bl-red); color:#fff; ${!canStart ? 'opacity:0.4; cursor:not-allowed;' : ''}" data-act="start-subround" data-game="${code}" data-subround="${r.round_number}" ${!canStart ? 'disabled' : ''}><span class="mi">play_arrow</span> Start Sub-Round ${r.round_number}</button>
                      `;
                    }

                    return `
                      <div style="display:flex; justify-content:space-between; align-items:center; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:8px 12px;">
                        <div style="display:flex; align-items:center; gap:10px;">
                          <span style="font-weight:700; font-size:0.88rem; color:#1e293b;">Sub-Round ${r.round_number}</span>
                          ${badgeHtml}
                        </div>
                        <div style="display:flex; align-items:center; gap:6px;">
                          ${actionButtonsHtml}
                        </div>
                      </div>
                    `;
                  }).join('') : `
                    <div style="font-size:0.85rem; color:#64748b; font-style:italic; text-align:center; padding:14px; background:#ffffff; border:1px dashed #cbd5e1; border-radius:6px;">
                      Session not started — Click "<span class="mi">play_circle</span> Start Session" above to configure sub-rounds count.
                    </div>
                  `}
                </div>
              </div>
            </div>
          `;
        }).join('')}
      </div>
    `;

    el.querySelectorAll('[data-act]').forEach((btn) => {
      const act = btn.dataset.act;
      const code = btn.dataset.game;
      btn.addEventListener('click', () => {
        if (act === 'start') {
          openStartModalForRound(code);
        } else if (act === 'start-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.startSubroundForRound(roundId, code, subnum)
            .then((res) => { toast(`Sub-round ${subnum} started in ${res.succeeded.length} rooms!`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'restart-subround') {
          const subnum = Number(btn.dataset.subround);
          if (!confirm(`Restart Sub-Round ${subnum} for ${GAMES[code]?.en} in ALL rooms? This resets ONLY Sub-Round ${subnum} so it can be re-played.`)) return;
          api.admin.restartSubroundForRound(roundId, code, subnum)
            .then((res) => { toast(`Sub-round ${subnum} restarted in ${res.succeeded.length} rooms!`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'show-results') {
          openResultsModal(code, roundId, gameSessions);
        } else if (act === 'publish') {
          if (!confirm(`Publish ${GAMES[code]?.en || code} results to ALL team screens in ALL rooms?`)) return;
          api.admin.publishGameForRound(roundId, code)
            .then(() => { toast(`Published ${GAMES[code]?.en || code} results to all team screens!`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'instructions') {
          if (!confirm(`Broadcast 5-minute instructions for ${GAMES[code]?.en} to all team screens?`)) return;
          api.admin.showInstructionsForRound(roundId, code)
            .then((res) => { toast(`Rules broadcasted successfully to all rooms!`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'pause') {
          if (!confirm(`Pause ${code} in ALL rooms?`)) return;
          api.admin.pauseSessionsForRound(roundId, code)
            .then((res) => { toast(`Paused in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'resume') {
          if (!confirm(`Resume ${code} in ALL rooms?`)) return;
          api.admin.resumeSessionsForRound(roundId, code)
            .then((res) => { toast(`Resumed in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'complete') {
          if (!confirm(`Force-complete and publish ${code} in ALL rooms?`)) return;
          api.admin.forceCompleteSessionsForRound(roundId, code)
            .then(() => api.admin.publishGameForRound(roundId, code))
            .then((res) => { toast(`Completed and published in all rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'restart') {
          if (!confirm(`RESTART ${code} in ALL rooms? This wipes all score data for this game!`)) return;
          api.admin.restartSessionsForRound(roundId, code)
            .then((res) => { toast(`Restarted in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-start') {
          openDemoStartModal(code);
        } else if (act === 'demo-restart') {
          // The practice-again control: deals a fresh attempt from any
          // state. No confirm — being able to hit it repeatedly without
          // friction is the whole point of a practice round.
          api.admin.demo.restart(roundId, code)
            .then((res) => { toast(`New demo attempt dealt in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-end') {
          if (!confirm(`End the ${GAMES[code]?.en || code} demo in ALL rooms? Team screens return to the real game.`)) return;
          api.admin.demo.end(roundId, code)
            .then((res) => { toast(`Demo ended in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-pause') {
          api.admin.demo.pause(roundId, code)
            .then((res) => { toast(`Demo paused in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-resume') {
          api.admin.demo.resume(roundId, code)
            .then((res) => { toast(`Demo resumed in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-start-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.demo.startSubround(roundId, code, subnum)
            .then((res) => { toast(`Demo sub-round ${subnum} started in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        } else if (act === 'demo-restart-subround') {
          const subnum = Number(btn.dataset.subround);
          api.admin.demo.restartSubround(roundId, code, subnum)
            .then((res) => { toast(`Demo sub-round ${subnum} replayed in ${res.succeeded.length} rooms`); load(); })
            .catch((err) => toast(err.message, { error: true }));
        }
      });
    });
  }

  /* ======================================================================
     Demo (practice) rounds
     ----------------------------------------------------------------------
     A parallel play surface teams can rehearse on. It lives entirely in
     Redis (see app/services/demo_service.py) — nothing played here reaches
     game_scores, the per-game result tables, room_results, or any
     leaderboard, so a demo can be started, replayed and thrown away as
     often as a room needs without touching the real standings.

     While a demo is live it takes over the team screens for that game;
     "End Demo" hands them straight back to the real session.
     ====================================================================== */

  function renderDemoPanel(code, demoSessions = []) {
    const demos = (demoSessions || []).filter((d) => d.game_code === code);
    const live = demos.length > 0;

    // Every room in a round is dealt the same demo shape, so the first is a
    // fair representative for the sub-round list; the counts below are
    // still summed across every room.
    const sample = live ? demos[0] : null;
    const subrounds = sample ? (sample.rounds || []) : [];
    const attempt = live ? Math.max(...demos.map((d) => d.attempt || 1)) : 0;
    const statuses = new Set(demos.map((d) => d.status));
    const isPaused = statuses.has('PAUSED');
    const isCompleted = live && [...statuses].every((st) => st === 'COMPLETED');

    const statusLabel = !live
      ? 'No demo running'
      : isPaused ? 'PAUSED'
      : isCompleted ? 'FINISHED'
      : 'RUNNING';
    const statusColor = !live ? '#64748b' : isPaused ? '#b45309' : isCompleted ? '#0f766e' : '#15803d';

    const totalTeams = demos.reduce((sum, d) => sum + (d.total_room_teams || 0), 0);

    const subroundRows = subrounds.map((r) => {
      // Sum this sub-round's submissions across every room.
      const submitted = demos.reduce((sum, d) => {
        const match = (d.rounds || []).find((x) => x.round_number === r.round_number);
        return sum + ((match && match.submitted_teams) ? match.submitted_teams.length : 0);
      }, 0);
      const started = !!r.start_time;
      const closed = !!r.is_closed;

      const badge = closed
        ? '<span style="background:#ccfbf1; color:#0f766e; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">DONE</span>'
        : started
        ? '<span style="background:#dcfce7; color:#166534; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">LIVE</span>'
        : '<span style="background:#f1f5f9; color:#64748b; padding:2px 8px; border-radius:12px; font-size:0.7rem; font-weight:700;">WAITING</span>';

      const action = started
        ? `<button class="btn" style="padding:4px 10px; font-size:0.75rem;" data-act="demo-restart-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">replay</span> Replay</button>`
        : `<button class="btn" style="padding:4px 10px; font-size:0.75rem;" data-act="demo-start-subround" data-game="${code}" data-subround="${r.round_number}"><span class="mi">play_arrow</span> Start</button>`;

      return `
        <div style="display:flex; justify-content:space-between; align-items:center; background:#ffffff; border:1px solid #fed7aa; border-radius:6px; padding:6px 10px;">
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
            <span style="font-weight:700; font-size:0.82rem; color:#7c2d12;">Demo Sub-Round ${r.round_number}</span>
            ${badge}
            <span style="font-size:0.74rem; color:#9a3412;">${submitted} / ${totalTeams} submitted</span>
          </div>
          <div>${action}</div>
        </div>
      `;
    }).join('');

    return `
      <div style="background:#fffbeb; border:1.5px solid #f59e0b; border-radius:10px; padding:12px; margin-bottom:16px;">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:10px;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span style="background:#b45309; color:#fff; font-size:0.66rem; font-weight:900; letter-spacing:0.1em; padding:3px 8px; border-radius:3px;">DEMO</span>
            <span style="font-size:0.8rem; font-weight:800; color:#7c2d12;">Practice Round</span>
            <span style="font-size:0.74rem; font-weight:800; color:${statusColor};">&#9679; ${statusLabel}</span>
            ${live && attempt > 1 ? `<span style="font-size:0.72rem; font-weight:700; color:#b45309;">Attempt ${attempt}</span>` : ''}
            ${live ? `<span style="font-size:0.72rem; color:#9a3412;">${demos.length} room${demos.length === 1 ? '' : 's'} &middot; ${totalTeams} teams</span>` : ''}
          </div>
          <div class="btn-row" style="gap:6px; flex-wrap:wrap;">
            ${live ? `
              <button class="btn primary" data-act="demo-restart" data-game="${code}"><span class="mi">replay</span> Practice Again</button>
              ${isPaused
                ? `<button class="btn" data-act="demo-resume" data-game="${code}"><span class="mi">play_arrow</span> Resume Demo</button>`
                : `<button class="btn" data-act="demo-pause" data-game="${code}"><span class="mi">pause</span> Pause Demo</button>`}
              <button class="btn danger" data-act="demo-end" data-game="${code}"><span class="mi">stop_circle</span> End Demo</button>
            ` : `
              <button class="btn primary" data-act="demo-start" data-game="${code}"><span class="mi">school</span> Start Demo</button>
            `}
          </div>
        </div>

        <p style="font-size:0.72rem; color:#9a3412; margin:0 0 ${live ? '10px' : '0'};">
          Practice play on the real game screens. Scores are computed live for the teams but are
          <strong>never written to the database</strong> — no game scores, no leaderboard, no qualification.
          ${live ? 'Teams see this instead of the real game until you end it.' : ''}
        </p>

        ${live ? `<div style="display:flex; flex-direction:column; gap:6px;">${subroundRows}</div>` : ''}
      </div>
    `;
  }

  function openDemoStartModal(code) {
    // MindMaze, Ace of Spades, and King of Diamonds all run fixed-length
    // auto-submit sub-rounds (see settings.mindmaze_round_seconds /
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

  function openResultsModal(code, roundId, initialSessions) {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    let modalPoll = null;
    let lastRenderedJson = '';

    backdrop.innerHTML = `
      <div class="modal" style="max-width:760px; width:95vw; max-height:90vh; display:flex; flex-direction:column;">
        <!-- Modal Top Header -->
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1.5px solid #e2e8f0; padding-bottom:12px; margin-bottom:12px;">
          <div>
            <div style="display:flex; align-items:center; gap:8px;">
              <h3 style="margin:0; font-size:1.3rem; font-weight:900; color:#0f172a;">
                <span class="mi" style="color:var(--bl-red);">military_tech</span> ${GAMES[code]?.en || code} — Live Results & Progress
              </h3>
              <span id="modal-header-badge" class="pill IN_PROGRESS" style="font-size:0.72rem;">LIVE</span>
            </div>
            <div style="font-size:0.75rem; color:#64748b; margin-top:2px;">
              Real-time verified submission tracking, computation status, and live view confirmations across all rooms.
            </div>
          </div>
          <div style="display:flex; align-items:center; gap:6px; font-size:0.75rem; font-weight:700; color:#16a34a; background:#f0fdf4; border:1px solid #bbf7d0; padding:3px 8px; border-radius:12px;">
            <span style="display:inline-block; width:7px; height:7px; background:#22c55e; border-radius:50%;"></span>
            Live Tracking
          </div>
        </div>

        <!-- Overall Summary Progress Card -->
        <div id="modal-summary-box" style="background:#ffffff; border:1.5px solid #e2e8f0; border-radius:10px; padding:12px 14px; margin-bottom:12px; display:grid; grid-template-columns: 1fr 1fr; gap:12px;">
        </div>

        <!-- Scrollable Room List -->
        <div id="modal-rooms-container" style="flex:1; overflow-y:auto; padding-right:4px;">
        </div>

        <!-- Modal Footer Actions -->
        <div class="btn-row" style="margin-top:14px; padding-top:12px; border-top:1.5px solid #e2e8f0; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
          <button type="button" class="btn success" id="publish-results-modal-btn">
            <span class="mi">cast</span> Publish Results to Teams
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

    function renderModalContent(gameSessions) {
      const sessList = gameSessions.filter(s => s.game_code === code || s.session?.game_code === code);
      const isJackHeart = code === 'JACK_HEART';

      const currentJson = JSON.stringify(sessList);
      if (currentJson === lastRenderedJson) return;
      lastRenderedJson = currentJson;

      let totalSubroundsAllRooms = 0;
      let closedSubroundsAllRooms = 0;
      let totalActiveTeamsAllRooms = 0;
      let publishedViewsAllRooms = 0;

      sessList.forEach(s => {
        const sessionObj = s.session || s;
        const rounds = s.rounds || s.session?.rounds || [];
        const activeRoomTeams = sessionObj.total_room_teams > 0 ? sessionObj.total_room_teams : Math.max(1, (rounds[0]?.submitted_teams?.length || 1));
        totalActiveTeamsAllRooms += activeRoomTeams;
        totalSubroundsAllRooms += rounds.length;
        closedSubroundsAllRooms += rounds.filter(r => r.is_closed).length;
        publishedViewsAllRooms += (sessionObj.published_viewed_teams || []).length;
      });

      const subroundsPct = totalSubroundsAllRooms > 0 ? Math.round((closedSubroundsAllRooms / totalSubroundsAllRooms) * 100) : 0;
      const publishedPct = totalActiveTeamsAllRooms > 0 ? Math.min(100, Math.round((publishedViewsAllRooms / totalActiveTeamsAllRooms) * 100)) : 0;
      const isGamePublished = sessList.some(s => (s.session || s).is_published);

      const headerBadge = backdrop.querySelector('#modal-header-badge');
      if (headerBadge) {
        headerBadge.className = `pill ${isGamePublished ? 'COMPLETED' : 'IN_PROGRESS'}`;
        headerBadge.textContent = isGamePublished ? 'PUBLISHED' : 'LIVE';
      }

      const summaryBox = backdrop.querySelector('#modal-summary-box');
      if (summaryBox) {
        summaryBox.innerHTML = `
          <div>
            <div style="display:flex; justify-content:space-between; font-size:0.78rem; font-weight:700; color:#334155; margin-bottom:3px;">
              <span>Total Sub-Rounds Completed</span>
              <span style="color:#2563eb;">${closedSubroundsAllRooms} / ${totalSubroundsAllRooms} (${subroundsPct}%)</span>
            </div>
            <div style="background:#e2e8f0; height:7px; border-radius:4px; overflow:hidden;">
              <div style="background:#2563eb; width:${subroundsPct}%; height:100%; transition: width 0.3s ease;"></div>
            </div>
          </div>

          <div>
            <div style="display:flex; justify-content:space-between; font-size:0.78rem; font-weight:700; color:#334155; margin-bottom:3px;">
              <span>Published Results Viewed (Active Teams)</span>
              <span style="color:${publishedPct === 100 ? '#16a34a' : '#ea580c'};">${publishedViewsAllRooms} / ${totalActiveTeamsAllRooms} (${publishedPct}%)</span>
            </div>
            <div style="background:#e2e8f0; height:7px; border-radius:4px; overflow:hidden;">
              <div style="background:${publishedPct === 100 ? '#16a34a' : '#ea580c'}; width:${publishedPct}%; height:100%; transition: width 0.3s ease;"></div>
            </div>
          </div>
        `;
      }

      const roomsContainer = backdrop.querySelector('#modal-rooms-container');
      const scrollTop = roomsContainer ? roomsContainer.scrollTop : 0;
      const openDetailKeys = new Set();
      if (roomsContainer) {
        roomsContainer.querySelectorAll('details[open]').forEach(el => {
          openDetailKeys.add(el.dataset.key || el.querySelector('summary')?.textContent || '');
        });
      }

      let roomsHtml = '';
      if (sessList.length === 0) {
        roomsHtml = `<div style="text-align:center; padding: 24px; color: #64748b; background: #f8fafc; border-radius: 8px;">No active or past sessions found for ${GAMES[code]?.en || code}.</div>`;
      } else {
        roomsHtml = sessList.map(s => {
          const sessionObj = s.session || s;
          const rounds = s.rounds || s.session?.rounds || [];
          const roomActiveTeams = sessionObj.total_room_teams > 0 ? sessionObj.total_room_teams : Math.max(1, (rounds[0]?.submitted_teams?.length || 1));
          const roomClosedCount = rounds.filter(r => r.is_closed).length;
          const roomProgressPct = rounds.length > 0 ? Math.round((roomClosedCount / rounds.length) * 100) : 0;
          const roomPublishedViewed = sessionObj.published_viewed_teams || [];
          const roomPublishedPct = roomActiveTeams > 0 ? Math.min(100, Math.round((roomPublishedViewed.length / roomActiveTeams) * 100)) : 0;

          const subroundsHtml = rounds.map(r => {
            const subDetails = r.submission_details || [];
            const submittedCount = (subDetails.length > 0) ? subDetails.length : ((r.submitted_teams && r.submitted_teams.length) || (r.submitted ? 1 : 0));
            const isClosed = Boolean(r.is_closed || (r.deadline && new Date(r.deadline) <= new Date()));
            const submitPct = roomActiveTeams > 0 ? Math.min(100, Math.round((submittedCount / roomActiveTeams) * 100)) : 0;
            const viewedTeams = r.viewed_teams || [];
            const viewedPct = roomActiveTeams > 0 ? Math.min(100, Math.round((viewedTeams.length / roomActiveTeams) * 100)) : 0;

            const submitBarColor = submitPct === 100 ? '#16a34a' : (submitPct > 0 ? '#2563eb' : '#cbd5e1');
            const computeStatusText = isClosed ? '✓ Scores Computed & Finalized' : (submittedCount > 0 ? '✓ Submitted (Rolls Up on Close)' : (r.start_time ? '⏳ In Progress (Awaiting Submissions)' : 'Pending Start'));
            const computeBarColor = isClosed ? '#16a34a' : (submittedCount > 0 ? '#2563eb' : (r.start_time ? '#f59e0b' : '#94a3b8'));
            const computePct = isClosed ? 100 : (submittedCount > 0 ? 75 : (r.start_time ? 25 : 0));
            const detailKey = `sub_${sessionObj.session_id}_${r.round_number}`;

            return `
              <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; margin-bottom: 10px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px;">
                  <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-weight:800; font-size:0.9rem; color:#0f172a;">Sub-Round ${r.round_number}</span>
                    <span class="pill ${isClosed ? 'COMPLETED' : (r.start_time ? 'IN_PROGRESS' : 'NOT_STARTED')}" style="font-size:0.7rem; padding:2px 8px;">
                      ${isClosed ? 'CLOSED' : (r.start_time ? 'ACTIVE' : 'NOT STARTED')}
                    </span>
                  </div>
                  <div style="font-size:0.75rem; color:#64748b; font-weight:600;">
                    ${r.deadline ? `Deadline: ${new Date(r.deadline).toLocaleTimeString()}` : ''}
                  </div>
                </div>

                <!-- Submissions Progress Bar -->
                <div style="margin-bottom: 8px;">
                  <div style="display:flex; justify-content:space-between; font-size:0.78rem; font-weight:700; color:#334155; margin-bottom: 3px;">
                    <span><span class="mi" style="font-size:0.85rem; vertical-align:middle;">send</span> Active Teams Submitted</span>
                    <span style="color:${submitBarColor};">${submittedCount} / ${roomActiveTeams} (${submitPct}%)</span>
                  </div>
                  <div style="background:#e2e8f0; height:7px; border-radius:4px; overflow:hidden;">
                    <div style="background:${submitBarColor}; width:${submitPct}%; height:100%; transition:width 0.3s ease;"></div>
                  </div>
                </div>

                <!-- Result Computation Progress -->
                <div style="margin-bottom: ${isJackHeart && r.round_number >= 2 ? '8px' : '4px'};">
                  <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#475569; margin-bottom: 3px;">
                    <span><span class="mi" style="font-size:0.82rem; vertical-align:middle;">calculate</span> Scores & Ranking Computed</span>
                    <span style="font-weight:700; color:${computeBarColor};">
                      ${computeStatusText}
                    </span>
                  </div>
                  <div style="background:#e2e8f0; height:5px; border-radius:3px; overflow:hidden;">
                    <div style="background:${computeBarColor}; width:${computePct}%; height:100%;"></div>
                  </div>
                </div>

                ${isJackHeart && r.round_number >= 2 ? `
                  <!-- Jack of Hearts Mid-Game Standings View Progress -->
                  <div style="margin-bottom: 6px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 8px;">
                    <div style="display:flex; justify-content:space-between; font-size:0.73rem; font-weight:700; color:#475569; margin-bottom:3px;">
                      <span><span class="mi" style="font-size:0.8rem; vertical-align:middle;">visibility</span> Teams Viewed Mid-Game Standings</span>
                      <span style="color:${viewedPct === 100 ? '#16a34a' : '#ea580c'};">${viewedTeams.length} / ${roomActiveTeams} (${viewedPct}%)</span>
                    </div>
                    <div style="background:#e2e8f0; height:5px; border-radius:3px; overflow:hidden;">
                      <div style="background:${viewedPct === 100 ? '#16a34a' : '#ea580c'}; width:${viewedPct}%; height:100%;"></div>
                    </div>
                  </div>
                ` : ''}

                <!-- Submissions Details -->
                ${subDetails.length > 0 ? `
                  <details data-key="${detailKey}" style="margin-top:8px;">
                    <summary style="font-size:0.75rem; font-weight:700; color:#2563eb; cursor:pointer;">
                      ▶ View Team Submissions & Timestamps (${subDetails.length})
                    </summary>
                    <div style="margin-top:6px; overflow-x:auto;">
                      <table style="width:100%; font-size:0.75rem; border-collapse:collapse;">
                        <thead>
                          <tr style="background:#f1f5f9; border-bottom:1px solid #e2e8f0;">
                            <th style="padding:4px 6px; text-align:left;">Team</th>
                            <th style="padding:4px 6px; text-align:left;">Time Submitted</th>
                            <th style="padding:4px 6px; text-align:left;">Result / Detail</th>
                          </tr>
                        </thead>
                        <tbody>
                          ${subDetails.map(sd => `
                            <tr style="border-bottom:1px solid #f1f5f9;">
                              <td style="padding:4px 6px; font-weight:700;">${sd.team_code} <span style="font-weight:normal; color:#64748b;">(${sd.team_name})</span></td>
                              <td style="padding:4px 6px; font-family:var(--font-mono); color:#0f172a;">${sd.submitted_at_str || '—'}</td>
                              <td style="padding:4px 6px; color:#166534; font-weight:600;">${sd.detail || (sd.score !== null ? `+${sd.score} pts` : 'Submitted')}</td>
                            </tr>
                          `).join('')}
                        </tbody>
                      </table>
                    </div>
                  </details>
                ` : ''}
              </div>
            `;
          }).join('');

          const activeTeamCodes = sessionObj.active_team_codes || [];
          const pendingViewTeams = activeTeamCodes.filter(t => !roomPublishedViewed.includes(t));

          return `
            <div style="background:#f8fafc; border:1.5px solid #e2e8f0; border-radius:10px; padding:14px; margin-bottom:16px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; flex-wrap:wrap; gap:6px;">
                <div>
                  <h4 style="margin:0; font-size:1.05rem; font-weight:900; color:#0f172a;">
                    Room ${sessionObj.room_code || sessionObj.room_id?.slice(0, 8) || '—'}
                  </h4>
                  <div style="font-size:0.75rem; color:#64748b; font-weight:600;">
                    ${roomActiveTeams} Active Teams · Session: <span class="pill ${sessionObj.status}" style="font-size:0.68rem; padding:1px 6px;">${sessionObj.status}</span>
                  </div>
                </div>

                <div style="min-width:180px;">
                  <div style="display:flex; justify-content:space-between; font-size:0.75rem; font-weight:700; color:#334155; margin-bottom:2px;">
                    <span>Overall Progress</span>
                    <span>${roomClosedCount}/${rounds.length} Sub-Rounds (${roomProgressPct}%)</span>
                  </div>
                  <div style="background:#e2e8f0; height:6px; border-radius:3px; overflow:hidden;">
                    <div style="background:${roomProgressPct === 100 ? '#16a34a' : '#3b82f6'}; width:${roomProgressPct}%; height:100%;"></div>
                  </div>
                </div>
              </div>

              ${sessionObj.is_published ? `
                <div style="background:#ecfdf5; border:1px solid #a7f3d0; border-radius:8px; padding:8px 10px; margin-bottom:12px;">
                  <div style="display:flex; justify-content:space-between; font-size:0.78rem; font-weight:800; color:#065f46; margin-bottom:4px;">
                    <span><span class="mi" style="font-size:0.85rem; vertical-align:middle;">verified</span> Published Results Viewed by Teams</span>
                    <span>${roomPublishedViewed.length} / ${roomActiveTeams} Teams (${roomPublishedPct}%)</span>
                  </div>
                  <div style="background:#d1fae5; height:6px; border-radius:3px; overflow:hidden;">
                    <div style="background:#10b981; width:${roomPublishedPct}%; height:100%; transition:width 0.3s ease;"></div>
                  </div>
                  <div style="display:flex; flex-direction:column; gap:4px; margin-top:6px; font-size:0.72rem;">
                    ${roomPublishedViewed.length > 0 ? `
                      <div style="color:#047857; font-weight:600;">
                        Confirmed (${roomPublishedViewed.length}): ${roomPublishedViewed.map(t => `<span style="background:#ffffff; border:1px solid #a7f3d0; padding:1px 6px; border-radius:4px; margin-right:4px; font-weight:700; color:#065f46;">✓ ${t}</span>`).join('')}
                      </div>
                    ` : ''}
                    ${pendingViewTeams.length > 0 ? `
                      <div style="color:#b45309; font-weight:600;">
                        Awaiting View (${pendingViewTeams.length}): ${pendingViewTeams.map(t => `<span style="background:#fffbeb; border:1px solid #fde68a; padding:1px 6px; border-radius:4px; margin-right:4px; font-weight:700; color:#92400e;">⏳ ${t}</span>`).join('')}
                      </div>
                    ` : ''}
                  </div>
                </div>
              ` : ''}

              ${subroundsHtml}
            </div>
          `;
        }).join('');
      }

      if (roomsContainer) {
        roomsContainer.innerHTML = roomsHtml;
        roomsContainer.scrollTop = scrollTop;
        roomsContainer.querySelectorAll('details').forEach(el => {
          const key = el.dataset.key || el.querySelector('summary')?.textContent || '';
          if (openDetailKeys.has(key)) el.open = true;
        });
      }
    }

    function closeModal() {
      if (modalPoll) {
        clearInterval(modalPoll);
        modalPoll = null;
      }
      backdrop.remove();
    }

    backdrop.querySelector('#close-results').onclick = closeModal;
    backdrop.querySelector('#publish-results-modal-btn').onclick = () => {
      if (!confirm(`Publish results for ${GAMES[code]?.en || code} to ALL team screens in ALL rooms?`)) return;
      api.admin.publishGameForRound(roundId, code)
        .then(() => { toast(`Published ${GAMES[code]?.en || code} results to all teams in all rooms!`); load(); })
        .catch(err => toast(err.message, { error: true }));
    };
    backdrop.querySelector('#force-complete-btn').onclick = () => {
      if (!confirm(`Force-complete ${GAMES[code]?.en || code} in ALL rooms and compute final scores?`)) return;
      api.admin.forceCompleteSessionsForRound(roundId, code)
        .then(res => { toast(`Completed in ${res.succeeded.length} rooms`); load(); })
        .catch(err => toast(err.message, { error: true }));
    };

    document.body.appendChild(backdrop);
    renderModalContent(initialSessions);

    modalPoll = setInterval(async () => {
      if (!backdrop.isConnected) {
        clearInterval(modalPoll);
        return;
      }
      try {
        const updatedSessions = await api.admin.getRoundGameSessions(roundId);
        renderModalContent(updatedSessions);
      } catch (_) {}
    }, 1500);

    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) closeModal(); });
  }



  function openStartModalForRound(code) {
    const isMindmaze = code === 'MINDMAZE';
    const isAceSpade = code === 'ACE_SPADE';
    // Aug 2026: King of Diamonds also now runs a fixed-length, auto-submit
    // sub-round (see session_service.start_session /
    // settings.king_diamond_round_seconds) — no admin-picked duration.
    const isKingDiamond = code === 'KING_DIAMOND';
    const hasFixedTiming = isMindmaze || isAceSpade || isKingDiamond;
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3>Start ${GAMES[code]?.en || code} in ALL Rooms</h3>
        <form id="start-round-form">
          ${isMindmaze ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              MindMaze plays 30s memorize + 30s input per sub-round. Sub-round 1 will start with 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : isAceSpade ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              Ace of Spades plays 30s memorize + 40s card recall per sub-round, each preceded by a short shuffle-and-deal animation. Sub-round 1 will start with 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : isKingDiamond ? `
            <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
              King of Diamonds runs a fixed 45s sub-round with auto-submit — no duration to configure. Sub-round 1 will start with 3,2,1 countdown, then you can trigger subsequent sub-rounds manually.
            </p>
          ` : `
            <div class="field"><label class="tier-label"><span class="primary">Duration (minutes)</span><span class="secondary">1–60, default 1</span></label><input name="duration" type="number" min="1" max="60" value="1" /></div>
          `}

          <div class="field"><label class="tier-label"><span class="primary">${hasFixedTiming ? 'Sub-rounds' : 'Rounds'}</span><span class="secondary">1–10, default 5</span></label><input name="rounds" type="number" min="1" max="10" value="5" /></div>
          <div class="btn-row">
            <button type="submit" class="btn primary">Start in all rooms</button>
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
      const duration = hasFixedTiming ? 1 : Number(fd.get('duration'));
      try {
        const res = await api.admin.startSessionForRound(roundId, code, duration, Number(fd.get('rounds')));
        backdrop.remove();
        toast(`Session started in ${res.succeeded.length} rooms!`);
        load();
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  function renderLineup(el, lineup, roundStatus) {
    const current = new Map((lineup || []).map((g) => [g.game_code, g.game_order]));
    el.innerHTML = `
      <table class="dtable">
        <thead><tr><th>Game</th><th>Order</th><th>In lineup</th><th></th></tr></thead>
        <tbody>
          ${ALL_GAMES.map((code, i) => `
            <tr>
              <td>${GAMES[code].en}</td>
              <td><input type="number" min="1" value="${current.get(code) ?? i + 1}" data-order="${code}" style="width:60px;" /></td>
              <td><input type="checkbox" data-toggle="${code}" ${current.has(code) ? 'checked' : ''} /></td>
              <td>${current.has(code) ? `<button class="btn danger" data-remove="${code}">Remove</button>` : ''}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div class="btn-row">
        <button id="save-lineup" class="btn primary">Save lineup (full replace)</button>
      </div>
      <p class="status-note" style="text-align:left;padding-left:0;">Replacing fails with 409 if any session in this round has already started.</p>
    `;

    el.querySelectorAll('[data-remove]').forEach((btn) =>
      btn.addEventListener('click', async () => {
        try {
          await api.admin.removeGameFromLineup(roundId, btn.dataset.remove);
          toast('Removed from lineup');
          load();
        } catch (err) { toast(err.message, { error: true }); }
      }));

    el.querySelector('#save-lineup').addEventListener('click', async () => {
      const entries = ALL_GAMES
        .filter((code) => el.querySelector(`[data-toggle="${code}"]`).checked)
        .map((code) => ({ game_code: code, game_order: Number(el.querySelector(`[data-order="${code}"]`).value) }));
      try {
        await api.admin.setGameLineup(roundId, entries);
        toast('Lineup saved');
        load();
      } catch (err) { toast(err.message, { error: true }); }
    });
  }

  function renderRooms(el, detail) {
    const rooms = detail.rooms || [];
    if (!rooms.length) { el.innerHTML = `<p class="status-note" style="text-align:left;padding-left:0;">No rooms.</p>`; return; }
    el.innerHTML = `
      <table class="dtable">
        <thead><tr><th>Room</th><th>Teams</th><th>Status</th><th></th></tr></thead>
        <tbody>
          ${rooms.map((r) => `
            <tr>
              <td class="mono">${r.room_code || r.room_number || r.room_id}</td>
              <td>${r.team_count ?? '—'}</td>
              <td><span class="pill ${r.status || 'NOT_STARTED'}">${(r.status || '').replace('_',' ')}</span></td>
              <td><a class="rowlink" href="#/rooms/${r.room_id}/${roundId}">Manage →</a></td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }


  // Fix §1.3: Qualification Rule UI.
  // Without this, fn_compute_room_results always falls back to COALESCE(top_n, 1)
  // meaning only 1 team per room ever qualifies, regardless of intent.
  async function renderQualificationRules(el, rid) {
    el.innerHTML = `<div class="spinner"></div>`;
    let rules = [];
    try {
      rules = await api.admin.qualificationRules(rid).catch(() => []);
    } catch (_) {}

    const globalRule = rules.find((r) => !r.room_id);
    const globalTopN = globalRule ? globalRule.top_n : 1;

    el.innerHTML = `
      <div style="border:1px solid var(--bl-border);border-radius:6px;padding:14px;background:rgba(255,255,255,0.02);">
        <p style="font-size:0.8rem;color:var(--bl-gray);margin-bottom:12px;">
          Controls how many teams advance from each room.
          Sets the <code>top_n</code> value used by <code>fn_compute_room_results</code>.
          Default is 1 if unset.
        </p>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <label style="font-size:0.85rem;">Teams to qualify per room:</label>
          <input id="qual-top-n" type="number" min="1" max="20" value="${globalTopN}"
            style="width:70px;padding:6px;background:var(--bl-bg);color:#fff;border:1px solid var(--bl-border);border-radius:4px;" />
          <button id="save-qual" class="btn primary">Save rule</button>
        </div>
        ${rules.length > 0 ? `
          <table class="dtable" style="margin-top:12px;">
            <thead><tr><th>Scope</th><th>Top-N</th><th></th></tr></thead>
            <tbody>
              ${rules.map((r) => `
                <tr>
                  <td>${r.room_id ? `Room ${r.room_id.slice(0, 8)}` : 'All rooms (global)'}</td>
                  <td>${r.top_n}</td>
                  <td></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        ` : ''}
      </div>
    `;

    el.querySelector('#save-qual').addEventListener('click', async () => {
      const topN = Number(el.querySelector('#qual-top-n').value);
      if (!topN || topN < 1) { toast('Enter a valid number ≥ 1', { error: true }); return; }
      try {
        await api.admin.setQualificationRule(rid, topN);
        toast(`Qualification rule set: top ${topN} per room`);
        renderQualificationRules(el, rid);
      } catch (err) { toast(err.message, { error: true }); }
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
