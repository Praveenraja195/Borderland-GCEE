import { api, apiFetch } from '../../../../shared/js/api.js?v=v51_typewriter_scoreboard';
import { renderGameScreen } from './shell.js?v=v51_typewriter_scoreboard';
import { toast } from '../../../../shared/js/ui.js?v=v51_typewriter_scoreboard';
import { translateError, demoNoteHTML } from '../../../../shared/js/copy.js?v=v51_typewriter_scoreboard';

function formatScore(n) {
  const val = Number(n ?? 0);
  return Number.isInteger(val) ? String(val) : val.toFixed(1);
}

// The shell hands us api.demo instead of api.team when a practice round is
// running (same method names, different endpoints — see shared/js/api.js).
function gameApi(ctx) {
  return ctx.gameApi || api.team;
}

function getDeterministicLitTiles(seed, count = 20, total = 256) {
  let h = 0;
  const str = String(seed || 'mindmaze_default');
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }

  function nextRandom() {
    h = (Math.imul(1664525, h) + 1013904223) | 0;
    return (h >>> 0) / 4294967296;
  }

  const litSet = new Set();
  while (litSet.size < count) {
    litSet.add(Math.floor(nextRandom() * total));
  }
  return litSet;
}

const GRID_SIZE = 16;
const MEMORIZE_DURATION = 30; // 30 seconds to memorize
const INPUT_DURATION = 30;     // 30 seconds to input/fill

export function renderMindmaze(root, navigate) {
  return renderGameScreen(root, navigate, {
    gameCode: 'MINDMAZE',
    apiGameCode: 'mindmaze',
    renderActive(container, ctx, { navigate, reload }) {
      mountRound(container, ctx, reload);
    },
  });
}

// Bug-fix batch (Aug 2026): sub-round indicator shown inside the game
// screen itself (not just the shared header), so it's visible in every
// state — playing, submitted/waiting, and the "submitted" hero screen.
function roundBadge(ctx) {
  if (!ctx.roundNumber) return '';
  const label = ctx.totalRounds ? `Round ${ctx.roundNumber} / ${ctx.totalRounds}` : `Round ${ctx.roundNumber}`;
  return `<div class="status-note" style="text-align:center;font-weight:700;color:var(--bl-gray);padding-bottom:4px;">${label}</div>`;
}

function renderScoreReveal(container, ctx, { score, correctTiles, mistakes }, onDone, initialSecs = 5) {
  const currentSubScore = score !== undefined && score !== null ? Number(score) : 0;
  let remaining = initialSecs;

  container.innerHTML = `
    ${roundBadge(ctx)}
    <div class="result-hero" style="text-align: center; padding: var(--gap-lg) var(--gap-md); max-width: 480px; margin: 0 auto;">
      <div style="font-size: 0.9rem; font-weight: 700; color: var(--bl-red); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px;">
        Sub-Round ${ctx.roundNumber || ''} Completed
      </div>
      <h2 style="font-size: 1.6rem; font-weight: 800; color: var(--bl-ink); margin: 0 0 16px;">
        送信完了 / Score Obtained
      </h2>
      ${demoNoteHTML(ctx.isDemo)}

      <div style="background: #ffffff; border: 2px solid var(--bl-red); border-radius: 12px; padding: 24px 16px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(229,57,53,0.12);">
        <div style="font-size: 0.85rem; font-weight: 600; color: var(--bl-gray); text-transform: uppercase;">Your Score This Sub-Round</div>
        <div class="score" style="font-family: var(--font-mono); font-size: 3.8rem; font-weight: 900; color: var(--bl-red); margin: 8px 0; line-height: 1;">
          +${formatScore(currentSubScore)} <span style="font-size: 1.4rem; font-weight: 700;">pts</span>
        </div>
        <div style="display: flex; justify-content: center; gap: 16px; margin-top: 14px; font-size: 0.9rem; font-weight: 600;">
          <span style="background: #f1f5f9; padding: 4px 12px; border-radius: 6px; color: #334155;">
            Correct Tiles: <strong style="color: #166534;">${correctTiles ?? 0} / 20</strong>
          </span>
          <span style="background: #f1f5f9; padding: 4px 12px; border-radius: 6px; color: #334155;">
            Mistakes: <strong style="color: #991b1b;">${mistakes ?? 0}</strong>
          </span>
        </div>
      </div>

      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; text-align: center;">
        <span style="font-size: 0.88rem; color: #64748b; font-weight: 600;">
          Next screen in <strong id="mm-reveal-timer" style="color: var(--bl-red); font-size: 1.1rem;">${remaining}s</strong>...
        </span>
      </div>
    </div>
  `;

  const timerEl = container.querySelector('#mm-reveal-timer');

  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    clearInterval(timer);
    if (typeof onDone === 'function') onDone();
  };

  const timer = setInterval(() => {
    remaining -= 1;
    if (timerEl) timerEl.textContent = `${remaining}s`;
    if (remaining <= 0) {
      finish();
    }
  }, 1000);
}

function renderWaitingScreen(container, ctx, { score, correctTiles, mistakes }) {
  const currentSubScore = score !== undefined && score !== null ? Number(score) : 0;

  // Calculate total score and sub-round history chips from session.rounds
  const rounds = ctx.session?.rounds || [];
  let totalScore = 0;
  const roundChips = [];

  rounds.forEach((r) => {
    let rScore = null;
    const isThisRoundSubmitted = (r.round_number === ctx.roundNumber && ctx.submitted) || (r.submitted && r.round_number !== ctx.roundNumber);
    if (r.round_number === ctx.roundNumber && ctx.submitted && score !== undefined && score !== null) {
      rScore = Number(score);
    } else if (r.score !== undefined && r.score !== null && r.submitted && r.round_number !== ctx.roundNumber) {
      rScore = Number(r.score);
    }

    if (rScore !== null && isThisRoundSubmitted) {
      totalScore += rScore;
      roundChips.push(`
        <span style="background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 12px; padding: 2px 8px; font-size: 0.75rem; font-weight: 600; color: #334155;">
          Sub ${r.round_number}: <strong>${formatScore(rScore)} pts</strong>
        </span>
      `);
    }
  });

  if (roundChips.length === 0 && ctx.submitted && (score !== undefined && score !== null)) {
    totalScore = currentSubScore;
    roundChips.push(`
      <span style="background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 12px; padding: 2px 8px; font-size: 0.75rem; font-weight: 600; color: #334155;">
        Sub ${ctx.roundNumber || 1}: <strong>${formatScore(currentSubScore)} pts</strong>
      </span>
    `);
  }

  const isAllDone = rounds.length > 0 && rounds.every((r) => r.is_closed || r.submitted);

  container.innerHTML = `
    ${roundBadge(ctx)}
    <div class="result-hero" style="text-align: center; padding: var(--gap-md) var(--gap-sm);">
      <!-- Sub-round score summary (only if submitted) -->
      ${ctx.submitted && (score !== null && score !== undefined) ? `
      <div style="background: #ffffff; border: 1px solid var(--bl-border); border-radius: 10px; padding: 14px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span style="font-size: 0.9rem; font-weight: 700; color: #1e293b;">
            Sub-Round ${ctx.roundNumber || ''} Result: <strong style="color: var(--bl-red); font-family: var(--font-mono);">+${formatScore(currentSubScore)} pts</strong>
          </span>
          <span style="font-size: 0.78rem; color: var(--bl-gray);">Correct: ${correctTiles ?? 0} / 20 · Mistakes: ${mistakes ?? 0}</span>
        </div>
        <div style="border-top: 1px dashed #e2e8f0; padding-top: 10px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
          <div style="font-size: 0.85rem; font-weight: 700; color: #1e293b;">
            Cumulative MindMaze Score: <span style="font-family: var(--font-mono); color: var(--bl-red); font-size: 1.1rem;">${formatScore(totalScore)} pts</span>
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            ${roundChips.join('')}
          </div>
        </div>
      </div>
      ` : (roundChips.length > 0 ? `
      <div style="background: #ffffff; border: 1px solid var(--bl-border); border-radius: 10px; padding: 14px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
          <div style="font-size: 0.85rem; font-weight: 700; color: #1e293b;">
            Current Cumulative Score: <span style="font-family: var(--font-mono); color: var(--bl-red); font-size: 1.1rem;">${formatScore(totalScore)} pts</span>
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            ${roundChips.join('')}
          </div>
        </div>
      </div>
      ` : '')}

      <div style="margin-top: 16px; padding: 16px 0;">
        <div class="spinner" style="width: 28px; height: 28px; margin: 0 auto 10px;"></div>
        ${isAllDone ? `
          <p class="status-note" style="color: var(--bl-ink); font-weight: 800; font-size: 1.15rem; margin-bottom: 4px;">
            全ラウンド終了 / All Rounds Finished
          </p>
          <p class="status-note" style="color: var(--bl-red); font-weight: 700; font-size: 0.92rem; line-height: 1.5;">
            結果発表をお待ちください…<br>
            <span style="color:#64748b; font-size:0.82rem;">Waiting for Admin to publish results…</span>
          </p>
        ` : `
          <p class="status-note" style="color: var(--bl-ink); font-weight: 700; font-size: 1rem; margin-bottom: 4px;">
            ${!ctx.submitted ? `サブラウンド ${ctx.roundNumber || 1} の開始をお待ちください` : '次のサブラウンドの開始をお待ちください'}
          </p>
          <p class="status-note" style="color: var(--bl-red); font-weight: 600; font-size: 0.85rem;">
            管理者による開始指示をお待ちください / Waiting for Admin to start next sub-round
          </p>
        `}
      </div>
    </div>
  `;
}

function mountRound(container, ctx, reload) {
  // If this sub-round is already submitted or closed:
  if (ctx.submitted || ctx.allClosed) {
    let revealData = {
      score: ctx.score,
      correctTiles: ctx.correctTiles,
      mistakes: ctx.mistakes,
    };
    const savedStr = localStorage.getItem(`bl_mm_reveal_${ctx.roundId}`);
    if (savedStr) {
      try {
        revealData = JSON.parse(savedStr);
      } catch (_) { }
    }

    renderWaitingScreen(container, ctx, revealData);
    return;
  }

  // Round is NOT submitted (e.g. fresh or restarted) -> clear any stale reveal / pick storage
  try {
    localStorage.removeItem(`bl_mm_reveal_${ctx.roundId}`);
  } catch (_) { }

  if (!ctx.startTime) {
    try {
      localStorage.removeItem(`bl_mm_state_${ctx.roundId}`);
    } catch (_) { }
    renderWaitingScreen(container, ctx, { score: null, correctTiles: null, mistakes: null });
    return;
  }

  const serverStartTs = new Date(ctx.startTime).getTime();

  // Try to load state from localStorage first
  let stateData = null;
  const savedStateStr = localStorage.getItem(`bl_mm_state_${ctx.roundId}`);
  if (savedStateStr) {
    try {
      stateData = JSON.parse(savedStateStr);
    } catch (_) { }
  }

  // If saved state is from an older run or different start timestamp, discard it!
  if (stateData && stateData.startTs && Math.abs(Number(stateData.startTs) - serverStartTs) > 3000) {
    stateData = null;
    try { localStorage.removeItem(`bl_mm_state_${ctx.roundId}`); } catch (_) { }
  }

  const total = GRID_SIZE * GRID_SIZE;
  const seedKey = ctx.roundId ? String(ctx.roundId) : (ctx.sessionId ? `${ctx.sessionId}_${ctx.roundNumber}` : `round_${ctx.roundNumber || 1}`);
  const lit = getDeterministicLitTiles(seedKey, 20, total);
  let picked = new Set();
  let moves = 0;
  let mistakes = 0;
  let startTs = serverStartTs;

  if (stateData) {
    if (Array.isArray(stateData.picked)) {
      picked = new Set(stateData.picked.map(Number));
    }
    moves = Number(stateData.moves || 0);
    mistakes = Number(stateData.mistakes || 0);
  } else {
    saveStateToStorage();
  }

  function saveStateToStorage() {
    localStorage.setItem(`bl_mm_state_${ctx.roundId}`, JSON.stringify({
      startTs,
      picked: Array.from(picked),
      moves,
      mistakes
    }));
  }

  function clearStateFromStorage() {
    localStorage.removeItem(`bl_mm_state_${ctx.roundId}`);
  }

  // The phase is a pure function of SERVER time, so every device flips from
  // memorize to input — and auto-submits — at the same instant, however late
  // it mounted and whatever its own clock says.
  const serverNow = () => (typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now());
  const displayEndsAt = startTs + MEMORIZE_DURATION * 1000;
  const selectionEndsAt = displayEndsAt + INPUT_DURATION * 1000;
  function phaseAt(nowMs) {
    if (nowMs < displayEndsAt) {
      return { phase: 'display', timeLeft: Math.ceil((displayEndsAt - nowMs) / 1000) };
    }
    return { phase: 'selection', timeLeft: Math.max(0, Math.ceil((selectionEndsAt - nowMs) / 1000)) };
  }
  const initialPhase = phaseAt(serverNow());
  let currentPhase = initialPhase.phase;
  let timeLeft = initialPhase.timeLeft;

  // Calculate cumulative score from previous submitted sub-rounds
  const rounds = ctx.session?.rounds || [];
  let totalScoreSoFar = 0;
  rounds.forEach((r) => {
    if (r.round_number < (ctx.roundNumber || 1) && r.submitted && r.score !== undefined && r.score !== null) {
      totalScoreSoFar += Number(r.score);
    }
  });

  const state = {
    phase: currentPhase, // 'display' or 'selection' or 'submitted'
    picked,
    moves,
    mistakes,
    startedAt: startTs + (MEMORIZE_DURATION * 1000), // selection phase start timestamp
    submitting: false,
    timeLeft,
  };

  container.innerHTML = `
    <div class="mm-arena-card" style="max-width: 440px; margin: 0 auto; display: flex; flex-direction: column;">
      <!-- Header: Fixed height 54px -->
      <div style="height: 54px; display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px;">
        <div>
          ${roundBadge(ctx)}
          <div class="countdown-wrap" style="padding: 0; flex: none; align-items: flex-start;">
            <div class="countdown-face" id="mm-timer" style="font-size: 2.2rem; line-height: 1; font-family: var(--font-mono); font-weight: 800;">00:30</div>
            <div class="countdown-label" id="phase-note" style="height: 16px; line-height: 16px; font-size: 0.76rem; font-weight: 700; color: var(--bl-red); margin-top: 2px;">
              ${state.phase === 'display' ? 'Phase 1: Memorize lit tiles…' : 'Phase 2: Tap memorized tiles…'}
            </div>
          </div>
        </div>
        
        <!-- Top-right Total Score Box -->
        <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px 10px; text-align: right; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-width: 84px;">
          <div style="font-size: 0.68rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em;">Total Score</div>
          <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 800; color: var(--bl-red); line-height: 1.1;">
            ${formatScore(totalScoreSoFar)} <span style="font-size: 0.72rem; font-weight: 700;">pts</span>
          </div>
        </div>
      </div>

      <!-- Rock-solid locked 16x16 Grid: Width 100%, Aspect-Ratio 1/1 -->
      <div class="mindmaze-grid" id="mm-grid" style="display: grid; grid-template-columns: repeat(${GRID_SIZE}, 1fr); gap: 2px; width: 100%; aspect-ratio: 1 / 1; box-sizing: border-box; background: #cbd5e1; padding: 2px; border-radius: 6px;"></div>

      <!-- Stat Row: Fixed height 24px -->
      <div class="mm-stat-row" style="height: 24px; display: flex; justify-content: space-between; align-items: center; padding: 2px 4px; font-size: 0.82rem; font-weight: 600; color: var(--bl-gray); margin-top: 6px;">
        <span id="mm-picked-count" style="color: var(--bl-ink);">Selected: ${state.picked.size} / 20</span>
        <span id="mm-moves">Moves: ${state.moves}</span>
      </div>

      <div class="status-note" style="text-align:center; font-size:0.78rem; color:var(--bl-red); margin-top:8px; font-weight:600; height: 18px; line-height: 18px;">
        Auto-submits when timer expires / 制限時間終了時に自動送信されます
      </div>
    </div>
  `;

  const grid = container.querySelector('#mm-grid');
  const timerFace = container.querySelector('#mm-timer');
  const phaseNote = container.querySelector('#phase-note');
  const movesEl = container.querySelector('#mm-moves');
  const pickedCountEl = container.querySelector('#mm-picked-count');

  const cells = [];
  for (let i = 0; i < total; i++) {
    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'mm-tile';
    cell.dataset.i = i;
    cell.style.cssText = `
      aspect-ratio: 1 / 1;
      width: 100%;
      height: 100%;
      min-width: 0;
      min-height: 0;
      padding: 0;
      margin: 0;
      border: none;
      border-radius: 2px;
      box-sizing: border-box;
      cursor: pointer;
      background: #ffffff;
    `;
    grid.appendChild(cell);
    cells.push(cell);
  }

  // Restore tiles state
  if (state.phase === 'display') {
    lit.forEach((i) => {
      if (cells[i]) {
        cells[i].style.background = '#0f172a';
        cells[i].classList.add('lit');
      }
    });
  } else {
    // Selection phase
    cells.forEach((cell, i) => {
      if (state.picked.has(i)) {
        cell.style.background = '#0f172a';
        cell.classList.add('picked');
      }
    });
    startSelectionPhase(true);
  }

  // Anti-cheat tab switch detection
  let tabSwitchHandled = false;

  function handleTabSwitch() {
    if (tabSwitchHandled || state.submitting || state.phase === 'submitted') return;
    if (!document.hidden && document.hasFocus && document.hasFocus()) return;

    tabSwitchHandled = true;
    cleanupTabSwitchListeners();

    if (state.phase === 'display') {
      state.picked = new Set();
      state.moves = 0;
      state.mistakes = 0;
      toast('Tab switch detected during memorization phase! Sub-round terminated with 0 points.', { error: true });
      submitResult(true);
    } else if (state.phase === 'selection') {
      toast('Tab switch detected! Sub-round auto-submitted with current selections.', { error: true });
      submitResult(true);
    }
  }

  function onVisibilityChange() {
    if (document.hidden) {
      handleTabSwitch();
    }
  }

  function onBlur() {
    handleTabSwitch();
  }

  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('blur', onBlur);

  function cleanupTabSwitchListeners() {
    document.removeEventListener('visibilitychange', onVisibilityChange);
    window.removeEventListener('blur', onBlur);
  }

  // Timer interval
  updateTimerDisplay();
  const timerInterval = setInterval(() => {
    if (!container.isConnected) {
      cleanupTabSwitchListeners();
      clearInterval(timerInterval);
      return;
    }

    if (state.phase === 'submitted') {
      cleanupTabSwitchListeners();
      clearInterval(timerInterval);
      return;
    }

    const p = phaseAt(serverNow());
    if (p.phase === 'selection' && state.phase === 'display') startSelectionPhase();
    state.timeLeft = p.timeLeft;
    updateTimerDisplay();

    if (state.phase === 'selection' && p.timeLeft <= 0) {
      clearInterval(timerInterval);
      autoSubmitResult();
    }
  }, 250);

  function updateTimerDisplay() {
    const secsStr = String(Math.max(state.timeLeft, 0)).padStart(2, '0');
    timerFace.textContent = `00:${secsStr}`;
  }

  function startSelectionPhase(isRestore = false) {
    state.phase = 'selection';
    if (!isRestore) {
      state.timeLeft = INPUT_DURATION;
      updateTimerDisplay();
    }
    if (phaseNote) {
      phaseNote.textContent = 'Phase 2: Tap memorized tiles…';
      phaseNote.style.color = '#166534';
    }

    // Clear lit display style
    cells.forEach((cell) => {
      cell.style.background = '#ffffff';
      cell.classList.remove('lit');
    });

    // Re-apply picked style
    state.picked.forEach((i) => {
      if (cells[i]) {
        cells[i].style.background = '#0f172a';
        cells[i].classList.add('picked');
      }
    });

    // Enable interaction
    cells.forEach((cell, i) => {
      cell.onclick = () => {
        if (state.phase !== 'selection') return;
        if (state.picked.has(i)) {
          // Deselect tile
          state.picked.delete(i);
          state.moves += 1;
          cell.classList.remove('picked');
          cell.style.background = '#ffffff';
        } else {
          // Select tile
          state.picked.add(i);
          state.moves += 1;
          cell.classList.add('picked');
          cell.style.background = '#0f172a';
        }
        if (movesEl) movesEl.textContent = `Moves: ${state.moves}`;
        if (pickedCountEl) pickedCountEl.textContent = `Selected: ${state.picked.size} / 20`;
        saveStateToStorage();
      };
    });
  }

  async function submitResult(isAuto = false) {
    if (state.submitting || state.phase === 'submitted') return;
    state.submitting = true;
    cleanupTabSwitchListeners();

    const correctTiles = [...state.picked].filter((i) => lit.has(Number(i))).length;
    const mistakes = [...state.picked].filter((i) => !lit.has(Number(i))).length;
    const moves = Math.max(state.moves, state.picked.size, correctTiles + mistakes);
    const completionTimeSeconds = state.startedAt ? Math.max(0, (serverNow() - state.startedAt) / 1000) : 0;

    try {
      const res = await gameApi(ctx).mindmazeSubmit(ctx.roundId, {
        moves,
        mistakes,
        correct_tiles: correctTiles,
        completion_time_seconds: completionTimeSeconds,
      });
      // Clear persistence upon successful submit
      clearStateFromStorage();
      clearInterval(timerInterval);
      state.phase = 'submitted';

      const revealData = {
        score: res.round_score,
        correctTiles: res.correct_tiles,
        mistakes: res.mistakes,
        submittedAt: Date.now(),
      };
      localStorage.setItem(`bl_mm_reveal_${ctx.roundId}`, JSON.stringify(revealData));

      renderScoreReveal(container, ctx, revealData, () => {
        renderWaitingScreen(container, ctx, revealData, reload);
      }, 5);
    } catch (err) {
      if (err.status === 409) {
        clearStateFromStorage();
        clearInterval(timerInterval);
        state.phase = 'submitted';

        const revealData = {
          score: ctx.score !== undefined && ctx.score !== null ? ctx.score : 0,
          correctTiles: ctx.correctTiles !== undefined && ctx.correctTiles !== null ? ctx.correctTiles : correctTiles,
          mistakes: ctx.mistakes !== undefined && ctx.mistakes !== null ? ctx.mistakes : mistakes,
          submittedAt: Date.now(),
        };
        localStorage.setItem(`bl_mm_reveal_${ctx.roundId}`, JSON.stringify(revealData));

        renderScoreReveal(container, ctx, revealData, () => {
          renderWaitingScreen(container, ctx, revealData, reload);
        }, 5);
        return;
      }

      const jp = translateError(err.detail);
      toast(jp ? `${jp} / ${err.message}` : err.message, { error: true });
      state.submitting = false;
    }
  }

  function autoSubmitResult() {
    if (state.submitting || state.phase === 'submitted') return;
    toast('Time expired! Submitting answers...', { error: false });
    submitResult(true);
  }
}