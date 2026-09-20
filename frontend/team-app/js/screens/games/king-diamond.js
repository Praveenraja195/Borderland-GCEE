import { api } from '../../../../shared/js/api.js?v=v64_login_hints';
import { renderGameScreen } from './shell.js?v=v64_login_hints';
import { toast } from '../../../../shared/js/ui.js?v=v64_login_hints';
import { translateError, demoNoteHTML } from '../../../../shared/js/copy.js?v=v64_login_hints';

// King of Diamonds: The room average x 0.8 target game.
// All teams start with (num_rounds * 20.0) total points for the entire game.
// Each sub-round deducts penalty based on nearness rank.

const REVEAL_SECONDS = 15;
const POLL_MS = 1000;
let activePoll = null; // { roundId, intervalId }

// Path to the blueprint scale backdrop used on the result-reveal screen.
// Update this to wherever kd_res_bg.png lives in your static assets.
const KD_BG_URL = '../../../../shared/assets/kd_res_bg.png';

// Path to the King of Diamonds loader card art (front face + card back).
// Update these to wherever the two images live in your static assets.
const KD_CARD_FRONT_URL = '../../../../shared/assets/kd_loader_front.webp';
const KD_CARD_BACK_URL = '../../../../shared/assets/kd_loader_backside.webp';

function getNow() {
  return typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now();
}

export function renderKingDiamond(root, navigate) {
  return renderGameScreen(root, navigate, {
    gameCode: 'KING_DIAMOND',
    apiGameCode: 'king-diamond',
    renderActive(container, ctx, { reload }) {
      injectKDStyles();
      mountRound(container, ctx, reload);
    },
  });
}

// ── CSS — Matrix selection UI (1-50 and 51-100 grids) ─────────────────
function injectKDStyles() {
  if (document.getElementById('kd-picker-styles')) return;
  const style = document.createElement('style');
  style.id = 'kd-picker-styles';
  style.textContent = `
    /* ── Picker root ── */
    .kd-p-root {
      max-width: 480px;
      margin: 0 auto;
      padding: 12px 14px 20px;
      background: #ffffff;
      border-radius: 16px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.06);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      box-sizing: border-box;
    }
    /* ── Top Display Card ── */
    .kd-p-display {
      border-radius: 14px;
      padding: 16px 18px 14px;
      margin-bottom: 12px;
      transition: all 0.2s ease;
    }
    /* Default / Unselected State: Light neutral background, soft light gray number */
    .kd-p-display.kd-p-state-default {
      background: #f8fafc;
      border: 1.5px dashed #cbd5e1;
      color: #475569;
    }
    .kd-p-display.kd-p-state-default .kd-p-display-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #64748b;
      font-weight: 700;
    }
    .kd-p-display.kd-p-state-default .kd-p-display-num {
      font-size: 3.6rem;
      font-weight: 700;
      color: #94a3b8;
      line-height: 1;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.02em;
      transition: transform 0.12s ease, opacity 0.12s ease;
    }
    .kd-p-display.kd-p-state-default .kd-p-display-hint {
      font-size: 0.72rem;
      color: #64748b;
      margin-top: 6px;
      line-height: 1.4;
    }

    /* Selected State: Dark background box with bold high-contrast text */
    .kd-p-display.kd-p-state-selected {
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      border: 1.5px solid #334155;
      color: #ffffff;
      box-shadow: 0 6px 18px rgba(15, 23, 42, 0.25);
    }
    .kd-p-display.kd-p-state-selected .kd-p-display-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      color: #94a3b8;
      font-weight: 700;
    }
    .kd-p-display.kd-p-state-selected .kd-p-display-num {
      font-size: 3.8rem;
      font-weight: 900;
      color: #ffffff;
      line-height: 1;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.02em;
      text-shadow: 0 2px 10px rgba(0,0,0,0.4);
      transition: transform 0.12s ease, opacity 0.12s ease;
    }
    .kd-p-display.kd-p-state-selected .kd-p-display-hint {
      font-size: 0.72rem;
      color: #cbd5e1;
      margin-top: 6px;
      line-height: 1.4;
    }

    .kd-p-display-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 6px;
    }
    .kd-p-display-main {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
    }
    .kd-p-display-num.kd-p-flash {
      animation: kd-p-num-flash 0.15s ease;
    }
    @keyframes kd-p-num-flash {
      0%   { opacity: 0.4; transform: scale(0.92); }
      100% { opacity: 1;   transform: scale(1); }
    }

    /* Badges */
    .kd-p-badge {
      font-size: 0.65rem;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 3px 9px;
      border-radius: 20px;
      transition: all 0.2s ease;
    }
    .kd-p-badge.kd-badge-selected {
      background: #22c55e;
      color: #ffffff;
      box-shadow: 0 0 8px rgba(34, 197, 94, 0.4);
    }
    .kd-p-badge.kd-badge-default {
      background: #e2e8f0;
      color: #64748b;
      border: 1px solid #cbd5e1;
    }

    /* ── Action Bar (Deselect only) ── */
    .kd-p-actions {
      display: flex;
      margin-bottom: 14px;
    }
    .kd-p-btn-deselect {
      width: 100%;
      background: #f1f5f9;
      color: #475569;
      border: 1.5px solid #cbd5e1;
      border-radius: 10px;
      padding: 10px 14px;
      font-size: 0.85rem;
      font-weight: 700;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .kd-p-btn-deselect:hover {
      background: #fee2e2;
      color: #dc2626;
      border-color: #fca5a5;
    }
    .kd-p-btn-deselect:active {
      transform: scale(0.97);
    }

    /* ── Matrix Section & Grids ── */
    .kd-m-section {
      margin-bottom: 14px;
    }
    .kd-m-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.82rem;
      font-weight: 700;
      color: #1e293b;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 8px;
      padding-bottom: 6px;
      border-bottom: 1.5px solid #e2e8f0;
    }

    /* 10 columns grid (10 × 5) */
    .kd-m-grid {
      display: grid;
      grid-template-columns: repeat(10, 1fr);
      gap: 5px;
    }

    /* Matrix Tile */
    .kd-m-tile {
      background: #f8fafc;
      border: 1.5px solid #e2e8f0;
      border-radius: 7px;
      padding: 9px 0;
      font-size: 0.85rem;
      font-weight: 600;
      color: #1e293b;
      cursor: pointer;
      text-align: center;
      line-height: 1;
      user-select: none;
      -webkit-tap-highlight-color: transparent;
      transition: all 0.12s cubic-bezier(0.2, 0.8, 0.4, 1);
    }
    .kd-m-tile:hover {
      background: #e2e8f0;
      border-color: #cbd5e1;
      transform: translateY(-1px);
    }
    .kd-m-tile:active {
      transform: scale(0.90);
    }

    /* Selected Tile State */
    .kd-m-tile.kd-m-selected {
      background: #e53935 !important;
      color: #ffffff !important;
      border-color: #b71c1c !important;
      font-weight: 800 !important;
      box-shadow: 0 3px 10px rgba(229, 57, 53, 0.45);
      transform: scale(1.08);
      z-index: 2;
    }

    .kd-p-auto-note {
      text-align: center;
      font-size: 0.72rem;
      color: #64748b;
      margin-top: 12px;
      font-weight: 600;
    }
  `;
  document.head.appendChild(style);
}

// ── CARD LOADER — realistic rotating King of Diamonds card ─────────────
function injectKDCardLoaderStyles() {
  if (document.getElementById('kd-card-loader-styles')) return;
  const style = document.createElement('style');
  style.id = 'kd-card-loader-styles';
  style.textContent = `
    .kd-card-loader-wrap {
      display: flex; justify-content: center; margin: 16px auto 12px;
    }
    .kd-card-loader {
      position: relative;
      width: 112px; height: 160px;
      perspective: 900px;
      animation: kd-card-float 2.8s ease-in-out infinite;
    }
    .kd-card-loader-inner {
      position: relative;
      width: 100%; height: 100%;
      transform-style: preserve-3d;
      animation:
        kd-card-spin 2.8s linear infinite,
        kd-card-shine-glow 2.8s ease-in-out infinite;
    }
    .kd-card-face {
      position: absolute; inset: 0;
      overflow: hidden;
      border-radius: 8px;
      background-size: cover; background-position: center;
      backface-visibility: hidden;
    }
    .kd-card-face-back { transform: rotateY(180deg); }
    /* diagonal light sweep — the only "shine", no colored halo behind the card */
    .kd-card-face::after {
      content: '';
      position: absolute; inset: 0;
      background: linear-gradient(115deg,
        transparent 32%,
        rgba(255,255,255,0.5) 48%,
        rgba(255,255,255,0.12) 54%,
        transparent 70%);
      transform: translateX(-130%);
      animation: kd-card-shine-sweep 2.8s ease-in-out infinite;
      pointer-events: none;
    }

    @keyframes kd-card-spin {
      from { transform: rotateY(0deg); }
      to   { transform: rotateY(360deg); }
    }
    @keyframes kd-card-float {
      0%, 100% { transform: translateY(0); }
      50%      { transform: translateY(-5px); }
    }
    /* soft light glow hugging the card's own silhouette — no rectangular tint */
    @keyframes kd-card-shine-glow {
      0%, 100% { filter: drop-shadow(0 3px 6px rgba(0,0,0,0.35)) drop-shadow(0 0 8px rgba(255,220,150,0.25)); }
      50%      { filter: drop-shadow(0 5px 10px rgba(0,0,0,0.4)) drop-shadow(0 0 18px rgba(255,225,170,0.55)); }
    }
    @keyframes kd-card-shine-sweep {
      0%, 40%  { transform: translateX(-130%); }
      65%      { transform: translateX(130%); }
      100%     { transform: translateX(130%); }
    }

    @media (prefers-reduced-motion: reduce) {
      .kd-card-loader, .kd-card-loader-inner, .kd-card-face::after { animation: none !important; }
    }
  `;
  document.head.appendChild(style);
}

function kdCardLoaderHTML() {
  injectKDCardLoaderStyles();
  return `
    <div class="kd-card-loader-wrap">
      <div class="kd-card-loader">
        <div class="kd-card-loader-inner">
          <div class="kd-card-face" style="background-image:url('${KD_CARD_FRONT_URL}');"></div>
          <div class="kd-card-face kd-card-face-back" style="background-image:url('${KD_CARD_BACK_URL}');"></div>
        </div>
      </div>
    </div>
  `;
}

// ── Utility ───────────────────────────────────────────────────────────
function formatScore(n) {
  const val = Number(n ?? 0);
  return Number.isInteger(val) ? String(val) : val.toFixed(1);
}

// The shell hands us api.demo instead of api.team when a practice round is
// running (same method names, different endpoints — see shared/js/api.js).
function gameApi(ctx) {
  return ctx.gameApi || api.team;
}

function formatNumber(n) {
  if (n === null || n === undefined) return '—';
  const val = Number(n);
  return Number.isInteger(val) ? String(val) : val.toFixed(2);
}

function roundBadge(ctx) {
  if (!ctx.roundNumber) return '';
  const label = ctx.totalRounds ? `Round ${ctx.roundNumber} / ${ctx.totalRounds}` : `Round ${ctx.roundNumber}`;
  return `<div class="status-note" style="text-align:center;font-weight:700;color:var(--bl-gray);padding-bottom:4px;">${label}</div>`;
}

// ── localStorage keys ─────────────────────────────────────────────────
function activeRoundKey(sessionId) { return `bl_kd_active_round_${sessionId}`; }
function shownKey(roundId) { return `bl_kd_shown_${roundId}`; }

// ── Mount router ──────────────────────────────────────────────────────
function mountRound(container, ctx, reload) {
  container.classList.add('kd-game-container');
  if (ctx.isClosed) {
    resumePendingRound(container, ctx, ctx.roundId, reload);
    return;
  }
  if (ctx.startTime) {
    if (ctx.submitted) {
      resumePendingRound(container, ctx, ctx.roundId, reload);
      return;
    }
    mountPicker(container, ctx, reload);
    return;
  }
  renderWaitingForNext(container, ctx, reload);
}

// ── PICKER — 10x5 matrix selection UI (1-50 and 51-100) ──────────────
function mountPicker(container, ctx, reload) {
  const sessionId = ctx.sessionId;
  const roundId = ctx.roundId;

  // Selection state: null means no number selected (will default to 50 when timer runs out)
  let selectedNum = null;
  let submitting = false;
  let submitted = false;
  let autoSubmitTimer = null;

  const deadlineMs = ctx.deadline
    ? new Date(ctx.deadline).getTime()
    : (getNow() + 45000);

  // Generate Matrix 1 tiles (1 to 50)
  let m1Tiles = '';
  for (let i = 1; i <= 50; i++) {
    m1Tiles += `<button class="kd-m-tile" data-num="${i}">${i}</button>`;
  }

  // Generate Matrix 2 tiles (51 to 100)
  let m2Tiles = '';
  for (let i = 51; i <= 100; i++) {
    m2Tiles += `<button class="kd-m-tile" data-num="${i}">${i}</button>`;
  }

  container.innerHTML = `
    ${roundBadge(ctx)}
    <div class="kd-p-root">
      <!-- Display Card -->
      <div class="kd-p-display kd-p-state-default" id="kd-p-display">
        <div class="kd-p-display-top">
          <span class="kd-p-display-label" id="kd-p-label">No Selection / 未選択</span>
          <span class="kd-p-badge kd-badge-default" id="kd-p-badge">DEFAULT: 50</span>
        </div>
        <div class="kd-p-display-main">
          <div class="kd-p-display-num" id="kd-p-num">—</div>
        </div>
        <div class="kd-p-display-hint" id="kd-p-hint">
          Select a number below. If timer runs out without a selection, 50 is used.
        </div>
      </div>

      <!-- Action bar (Deselect button only when selected) -->
      <div class="kd-p-actions">
        <button class="kd-p-btn-deselect" id="kd-p-deselect" style="display: none;">✕ Deselect / 選択解除</button>
      </div>

      <!-- Single Common Section for Matrix Selection -->
      <div class="kd-m-section">
        <div class="kd-m-header">
          <span>Select a Number / 数字を選択</span>
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="font-size:0.68rem; color:#64748b; font-weight:600;">Option 0:</span>
            <button class="kd-m-tile" data-num="0" style="padding: 3px 10px; font-size: 0.78rem;">0</button>
          </div>
        </div>
        <!-- 1 to 50 matrix grid -->
        <div class="kd-m-grid" style="margin-bottom: 8px;">
          ${m1Tiles}
        </div>
        <!-- 51 to 100 matrix grid -->
        <div class="kd-m-grid">
          ${m2Tiles}
        </div>
      </div>

      <div class="kd-p-auto-note">⏱ タイマー終了時に自動送信 / Auto-submits when timer runs out</div>
    </div>
  `;

  // ── Sync UI with selectedNum state ──
  function updateUI() {
    // Update tile selection highlight
    container.querySelectorAll('.kd-m-tile').forEach((tile) => {
      const num = parseInt(tile.dataset.num, 10);
      if (selectedNum !== null && num === selectedNum) {
        tile.classList.add('kd-m-selected');
      } else {
        tile.classList.remove('kd-m-selected');
      }
    });

    const displayCard = container.querySelector('#kd-p-display');
    const labelEl = container.querySelector('#kd-p-label');
    const numEl = container.querySelector('#kd-p-num');
    const badgeEl = container.querySelector('#kd-p-badge');
    const hintEl = container.querySelector('#kd-p-hint');
    const deselectBtn = container.querySelector('#kd-p-deselect');

    if (selectedNum !== null) {
      if (displayCard) displayCard.className = 'kd-p-display kd-p-state-selected';
      if (labelEl) labelEl.textContent = 'Selected Number / 選択した数字';
      if (numEl) numEl.textContent = String(selectedNum);
      if (badgeEl) {
        badgeEl.textContent = 'SELECTED';
        badgeEl.className = 'kd-p-badge kd-badge-selected';
      }
      if (hintEl) hintEl.textContent = `Number ${selectedNum} selected. Auto-submits when timer expires.`;
      if (deselectBtn) deselectBtn.style.display = 'block';
    } else {
      if (displayCard) displayCard.className = 'kd-p-display kd-p-state-default';
      if (labelEl) labelEl.textContent = 'No Selection / 未選択';
      if (numEl) numEl.textContent = '—';
      if (badgeEl) {
        badgeEl.textContent = 'DEFAULT: 50';
        badgeEl.className = 'kd-p-badge kd-badge-default';
      }
      if (hintEl) hintEl.textContent = 'Select a number below. If timer runs out without a selection, 50 is used.';
      if (deselectBtn) deselectBtn.style.display = 'none';
    }

    if (numEl) {
      numEl.classList.remove('kd-p-flash');
      void numEl.offsetWidth;
      numEl.classList.add('kd-p-flash');
    }
  }

  // ── Click delegation ──
  container.addEventListener('click', (e) => {
    const tile = e.target.closest('.kd-m-tile');
    if (tile) {
      const num = parseInt(tile.dataset.num, 10);
      if (selectedNum === num) {
        selectedNum = null; // Deselect!
      } else {
        selectedNum = num; // Select!
      }
      updateUI();
      return;
    }

    const deselectBtn = e.target.closest('#kd-p-deselect');
    if (deselectBtn) {
      selectedNum = null;
      updateUI();
      return;
    }
  });

  // ── Auto-submit at deadline ──
  autoSubmitTimer = setTimeout(() => doSubmit(), Math.max(0, deadlineMs - getNow()));

  async function doSubmit() {
    if (submitting || submitted) return;
    submitting = true;
    if (autoSubmitTimer) { clearTimeout(autoSubmitTimer); autoSubmitTimer = null; }

    // If selectedNum is chosen, use it. Otherwise default to 50!
    const finalValue = selectedNum !== null ? selectedNum : 50;

    try {
      await gameApi(ctx).kingDiamondSubmit(roundId, finalValue);
    } catch (err) {
      if (err.status !== 409) {
        const jp = translateError(err.detail);
        toast(jp ? `${jp} / ${err.message}` : err.message, { error: true });
      }
    }

    submitted = true;
    try { localStorage.setItem(activeRoundKey(sessionId), roundId); } catch (_) { }
    resumePendingRound(container, ctx, roundId, reload);
  }
}

// ── PENDING — poll until closed ───────────────────────────────────────
function resumePendingRound(container, ctx, roundId, reload) {
  showComputingScreen(container, ctx);
  if (activePoll && activePoll.roundId === roundId) return;
  if (activePoll) { clearInterval(activePoll.intervalId); activePoll = null; }

  const poll = async () => {
    let res;
    try {
      res = await gameApi(ctx).kingDiamondResult(roundId);
    } catch (_) {
      return;
    }
    if (res && res.is_closed) {
      if (activePoll) { clearInterval(activePoll.intervalId); activePoll = null; }
      const activeEl = container.isConnected
        ? container
        : document.querySelector('.kd-game-container') || container;
      showComputationReveal(activeEl, ctx, res, roundId, reload);
    }
  };

  const intervalId = setInterval(poll, POLL_MS);
  activePoll = { roundId, intervalId };
  poll();
}

// ── COMPUTING screen — original ───────────────────────────────────────
function showComputingScreen(container, ctx) {
  container.innerHTML = `
    ${roundBadge(ctx)}
    ${demoNoteHTML(ctx.isDemo)}
    <div class="result-hero" style="text-align: center; padding: var(--gap-lg) var(--gap-md); max-width: 440px; margin: 0 auto;">
      <p class="status-note" style="font-weight: 700; color: var(--bl-ink); font-size: 1.1rem; margin-bottom: 8px;">
        ✅ 送信完了 / Submitted
      </p>
      <div class="spinner" style="margin: var(--gap-md) auto; width: 32px; height: 32px;"></div>
      <p class="status-note" style="color: var(--bl-red); font-weight: 600; line-height: 1.5;">
        全チームの回答を集計中…<br>
        <span style="font-size: 0.85rem; color: #64748b;">Computing results…</span>
      </p>
    </div>
  `;
}

// ── REVEAL — animated blueprint-scale sequence ─────────────────────────
// The 15s "Next in..." countdown starts the instant this screen mounts,
// and the whole choreography (teams appear → numbers count up → avg × 0.8
// computed live → beam settles on the winner → deductions drop in → your
// remaining points count down) is budgeted to finish inside that same
// window, so nothing is stacked on top of the 15s — it all happens within it.
async function showComputationReveal(container, ctx, result, roundId, reload) {
  let timerDone = false;
  function finishReveal() {
    if (timerDone) return;
    timerDone = true;
    clearInterval(timerHandle);
    try { localStorage.setItem(shownKey(roundId), '1'); } catch (_) { }
    if (container.isConnected) {
      if (reload) reload();
      else renderWaitingForNext(container, ctx, reload);
    }
  }

  let timerHandle = null;

  await runKDReveal(container, {
    ctx,
    result,
    bgUrl: KD_BG_URL,
    onDone({ timerEl, nextBtn }) {
      let remaining = REVEAL_SECONDS;
      if (nextBtn) nextBtn.addEventListener('click', finishReveal);
      timerHandle = setInterval(() => {
        remaining -= 1;
        if (timerEl) timerEl.textContent = `${remaining}s`;
        if (remaining <= 0) finishReveal();
      }, 1000);
    },
  });
}

// ── WAITING — original ────────────────────────────────────────────────
function renderWaitingForNext(container, ctx, _reload) {
  const rounds = ctx.session?.rounds || [];
  const totalRounds = rounds.length || ctx.totalRounds || 5;
  const totalBasePoints = totalRounds * 20.0;
  let totalPenalty = 0;
  const chips = [];

  rounds.forEach((r) => {
    if (r.is_closed && r.score !== null && r.score !== undefined) {
      totalPenalty += Number(r.score);
      chips.push(`
        <span style="background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 12px; padding: 2px 8px; font-size: 0.75rem; font-weight: 600; color: #334155;">
          Sub ${r.round_number}: <strong>-${formatScore(r.score)}</strong>
        </span>
      `);
    }
  });

  const remainingScore = Math.max(0, totalBasePoints - totalPenalty);
  const closedCount = rounds.filter(r => r.is_closed).length;
  const isAllDone = rounds.length > 0 && closedCount >= rounds.length;
  const nextRoundNum = closedCount + 1;

  container.innerHTML = `
    <div style="text-align:center;font-weight:700;color:var(--bl-gray);padding-bottom:4px;">King of Diamonds</div>
    ${demoNoteHTML(ctx.isDemo)}
    <div class="result-hero" style="text-align: center; padding: var(--gap-md) var(--gap-sm); max-width: 480px; margin: 0 auto;">
      <div style="background: #ffffff; border: 1px solid var(--bl-border); border-radius: 10px; padding: 14px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="font-size: 0.85rem; font-weight: 700; color: #1e293b;">
          Remaining Points / 残りポイント: <span style="font-family: var(--font-mono); color: var(--bl-red); font-size: 1.2rem;">${formatScore(remainingScore)} / ${totalBasePoints} pts</span>
        </div>
        ${chips.length ? `<div style="display:flex; gap:6px; flex-wrap:wrap; justify-content:center; margin-top:10px;">${chips.join('')}</div>` : ''}
      </div>
      ${kdCardLoaderHTML()}
      ${isAllDone ? `
        <p class="status-note" style="color: var(--bl-ink); font-weight: 800; font-size: 1.2rem; margin-bottom: 6px;">
          全ラウンド終了 / All Rounds Finished
        </p>
        <p class="status-note" style="color: var(--bl-red); font-weight: 700; font-size: 0.95rem; line-height: 1.5;">
          結果発表をお待ちください…<br>
          <span style="color:#64748b; font-size:0.85rem;">Waiting for Admin to publish results…</span>
        </p>
      ` : `
        <p class="status-note" style="color: var(--bl-ink); font-weight: 700; font-size: 1.05rem; margin-bottom: 6px;">
          次のサブラウンドの開始をお待ちください
        </p>
        <p class="status-note" style="color: var(--bl-red); font-weight: 600; font-size: 0.88rem; line-height: 1.5;">
          管理者による開始指示をお待ちください<br>
          <span style="color:#64748b; font-size:0.8rem;">Waiting for Admin to start Sub-Round ${nextRoundNum}</span>
        </p>
      `}
    </div>
  `;
}

/* =========================================================================
   KING OF DIAMONDS — animated result reveal
   Blueprint-scale aesthetic, built on kd_res_bg as backdrop.
   Sequence: teams appear -> numbers appear -> avg x0.8 calc -> winner ->
             deductions -> your remaining points -> continue.
   ========================================================================= */

function injectKDRevealStyles(bgUrl) {
  if (document.getElementById('kd-rv-styles')) return;
  const style = document.createElement('style');
  style.id = 'kd-rv-styles';
  style.textContent = `
    .kd-rv-root {
      position: relative;
      max-width: 480px;
      margin: 0 auto;
      border-radius: 18px;
      overflow: hidden;
      background: #060c18 url('${bgUrl}') center top / cover no-repeat;
      color: #eaf2fb;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      box-shadow: 0 18px 44px rgba(0,0,0,0.45);
      padding: 22px 16px 18px;
      box-sizing: border-box;
    }
    .kd-rv-root::before {
      content: '';
      position: absolute; inset: 0;
      background: linear-gradient(180deg, rgba(4,10,22,0.72) 0%, rgba(4,10,22,0.55) 38%, rgba(4,10,22,0.86) 100%);
      pointer-events: none;
    }
    .kd-rv-root > * { position: relative; z-index: 1; }

    .kd-rv-eyebrow {
      text-align: center; text-transform: uppercase; letter-spacing: 0.18em;
      font-size: 0.68rem; font-weight: 700; color: #7dd3fc; opacity: 0;
      animation: kd-rv-fade-down 0.5s ease forwards;
    }
    .kd-rv-title {
      text-align: center; font-size: 1.3rem; font-weight: 800; color: #fff;
      margin: 2px 0 16px; opacity: 0; animation: kd-rv-fade-down 0.5s ease 0.1s forwards;
      text-shadow: 0 0 18px rgba(125,211,252,0.35);
    }

    /* ---- beam: a thin scale line that wobbles while "weighing" ---- */
    .kd-rv-beam-wrap { height: 26px; margin-bottom: 6px; display: flex; align-items: center; justify-content: center; }
    .kd-rv-beam {
      width: 78%; height: 2px; background: linear-gradient(90deg, transparent, #7dd3fc, transparent);
      transform-origin: center; opacity: 0.55;
      transition: transform 0.5s ease, opacity 0.5s ease, filter 0.5s ease;
    }
    .kd-rv-beam.kd-rv-weighing { animation: kd-rv-beam-wobble 1.1s ease-in-out infinite; }
    .kd-rv-beam.kd-rv-settled { transform: rotate(0deg) !important; opacity: 1; filter: drop-shadow(0 0 6px #e53935); background: linear-gradient(90deg, transparent, #e53935, transparent); }
    @keyframes kd-rv-beam-wobble {
      0%, 100% { transform: rotate(-3.5deg); }
      50% { transform: rotate(3.5deg); }
    }

    /* ---- team cards ---- */
    .kd-rv-teams {
      display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-bottom: 14px;
    }
    .kd-rv-card {
      width: 84px; padding: 10px 6px 8px; border-radius: 12px;
      background: rgba(15,26,46,0.55); border: 1px solid rgba(125,211,252,0.25);
      text-align: center; opacity: 0; transform: translateY(16px) scale(0.94);
      transition: opacity 0.45s ease, transform 0.45s ease, border-color 0.4s ease, box-shadow 0.4s ease, filter 0.4s ease;
    }
    .kd-rv-card.kd-rv-in { opacity: 1; transform: translateY(0) scale(1); }
    .kd-rv-card.kd-rv-you { border-color: rgba(125,211,252,0.6); box-shadow: 0 0 0 1px rgba(125,211,252,0.25); }
    .kd-rv-card.kd-rv-winner {
      border-color: #e53935; background: rgba(65,10,10,0.55);
      box-shadow: 0 0 0 1px #e53935, 0 0 22px rgba(229,57,53,0.55);
      transform: translateY(0) scale(1.08);
    }
    .kd-rv-card.kd-rv-dim { opacity: 0.42; filter: grayscale(0.4); transform: translateY(0) scale(0.96); }

    .kd-rv-icon {
      width: 40px; height: 40px; margin: 0 auto 6px; border-radius: 50%;
      border: 1.5px solid #7dd3fc; display: flex; align-items: center; justify-content: center;
      font-family: var(--font-mono, ui-monospace, monospace); font-weight: 700; font-size: 0.85rem;
      color: #dff2ff; background: radial-gradient(circle at 35% 30%, rgba(125,211,252,0.22), transparent 70%);
      box-shadow: 0 0 10px rgba(125,211,252,0.25) inset;
    }
    .kd-rv-card.kd-rv-winner .kd-rv-icon { border-color: #ff8a80; color: #fff; box-shadow: 0 0 12px rgba(229,57,53,0.6); }
    .kd-rv-name { font-size: 0.66rem; font-weight: 700; letter-spacing: 0.03em; color: #b9cee2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .kd-rv-card.kd-rv-you .kd-rv-name::after { content: ' (YOU)'; color: #7dd3fc; }
    /* winner takes priority visually even when it's also your card */
    .kd-rv-card.kd-rv-winner.kd-rv-you { box-shadow: 0 0 0 1px #e53935, 0 0 22px rgba(229,57,53,0.55); }
    .kd-rv-card.kd-rv-winner.kd-rv-you .kd-rv-name::after { color: #ffd0cd; }
    .kd-rv-number {
      font-family: var(--font-mono, ui-monospace, monospace); font-size: 1.3rem; font-weight: 800;
      color: #fff; margin-top: 2px; min-height: 1.4rem;
    }
    .kd-rv-win-flag {
      display: inline-block; margin-top: 3px; font-size: 0.58rem; font-weight: 800; letter-spacing: 0.08em;
      color: #fff; background: #e53935; border-radius: 5px; padding: 1px 5px;
      opacity: 0; transform: scale(0.6); transition: opacity 0.3s ease, transform 0.3s ease;
    }
    .kd-rv-card.kd-rv-winner .kd-rv-win-flag { opacity: 1; transform: scale(1); }
    .kd-rv-deduct {
      margin-top: 4px; font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.72rem; font-weight: 700;
      color: #ff8a80; opacity: 0; transform: translateY(-6px);
      transition: opacity 0.35s ease, transform 0.35s ease;
    }
    .kd-rv-deduct.kd-rv-in { opacity: 1; transform: translateY(0); }

    /* ---- calc panel ---- */
    .kd-rv-calc {
      background: rgba(8,16,32,0.62); border: 1px solid rgba(125,211,252,0.28); border-radius: 12px;
      padding: 12px 14px; margin-bottom: 14px; opacity: 0; transform: translateY(8px);
      transition: opacity 0.5s ease, transform 0.5s ease;
    }
    .kd-rv-calc.kd-rv-in { opacity: 1; transform: translateY(0); }
    .kd-rv-calc-label { font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.12em; color: #7dd3fc; font-weight: 700; margin-bottom: 5px; }
    .kd-rv-formula { font-family: var(--font-mono, ui-monospace, monospace); font-size: 0.78rem; color: #cfe4f5; line-height: 1.5; min-height: 1.2em; }
    .kd-rv-target-row { display: flex; align-items: baseline; justify-content: space-between; margin-top: 6px; }
    .kd-rv-target-label { font-size: 0.72rem; color: #9db6cc; }
    .kd-rv-target {
      font-family: var(--font-mono, ui-monospace, monospace); font-size: 1.6rem; font-weight: 900; color: #e53935;
      opacity: 0; transition: opacity 0.4s ease; text-shadow: 0 0 16px rgba(229,57,53,0.5);
    }
    .kd-rv-target.kd-rv-in { opacity: 1; }

    /* ---- your points panel ---- */
    .kd-rv-points {
      background: linear-gradient(180deg, rgba(229,57,53,0.16), rgba(20,6,8,0.5));
      border: 1.5px solid #e53935; border-radius: 14px; padding: 14px; text-align: center;
      margin-bottom: 14px; opacity: 0; transform: scale(0.92);
      transition: opacity 0.5s ease, transform 0.5s ease;
    }
    .kd-rv-points.kd-rv-in { opacity: 1; transform: scale(1); }
    .kd-rv-points-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.1em; color: #ffb4ae; font-weight: 700; }
    .kd-rv-points-num {
      font-family: var(--font-mono, ui-monospace, monospace); font-size: 2.6rem; font-weight: 900; color: #fff;
      line-height: 1.1; margin: 3px 0; text-shadow: 0 0 20px rgba(229,57,53,0.55);
    }
    .kd-rv-points-sub { font-size: 0.78rem; color: #d9c3c1; }

    /* ---- footer / continue ---- */
    .kd-rv-footer {
      display: flex; align-items: center; justify-content: space-between;
      background: rgba(10,18,34,0.7); border: 1px solid rgba(125,211,252,0.22); border-radius: 10px;
      padding: 10px 14px; opacity: 0; transition: opacity 0.4s ease;
    }
    .kd-rv-footer.kd-rv-in { opacity: 1; }
    .kd-rv-footer-txt { font-size: 0.85rem; color: #b9cee2; font-weight: 600; }
    .kd-rv-footer-txt strong { color: #ff8a80; font-size: 1.05rem; }
    .kd-rv-next-btn {
      padding: 7px 16px; font-size: 0.85rem; font-weight: 700; background: #e53935; color: #fff;
      border: none; border-radius: 7px; cursor: pointer;
    }
    .kd-rv-next-btn:active { transform: scale(0.96); }

    @keyframes kd-rv-fade-down {
      from { opacity: 0; transform: translateY(-6px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes kd-rv-pop {
      0% { transform: scale(1); }
      50% { transform: scale(1.18); }
      100% { transform: scale(1); }
    }
    .kd-rv-pop { animation: kd-rv-pop 0.35s ease; }

    @media (prefers-reduced-motion: reduce) {
      .kd-rv-root * { animation: none !important; transition: none !important; }
    }
  `;
  document.head.appendChild(style);
}

function kdInitials(code) {
  const clean = String(code || '?').trim();
  const parts = clean.split(/[\s_-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

function kdDelay(ms) { return new Promise((res) => setTimeout(res, ms)); }

function kdCountUp(el, to, duration) {
  return new Promise((resolve) => {
    const start = performance.now();
    const target = Number(to) || 0;
    function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased);
      if (p < 1) requestAnimationFrame(tick);
      else { el.textContent = Number.isInteger(target) ? target : target.toFixed(2); resolve(); }
    }
    requestAnimationFrame(tick);
  });
}

// Fits a per-item stagger delay into a fixed time budget, so the entrance
// choreography takes roughly the same wall-clock time whether there are
// 3 teams or 10 — needed to keep the whole reveal inside REVEAL_SECONDS.
function kdStagger(n, budgetMs, min, max) {
  if (n <= 0) return 0;
  return Math.max(min, Math.min(max, budgetMs / n));
}

/**
 * Renders and animates the full King of Diamonds reveal sequence.
 * `result` is the same payload already produced by the round-result endpoint
 * (all_submissions, average_value, target_value, base_points, round_score, penalty...).
 * `onDone(withTimerEls)` is called immediately once the footer/timer exist,
 * receiving {timerEl, nextBtn}, so the caller's countdown starts at the same
 * moment the reveal starts — the whole animated sequence is budgeted to
 * finish comfortably inside that same window, not stacked after it.
 */
async function runKDReveal(container, { ctx, result, bgUrl, onDone }) {
  injectKDRevealStyles(bgUrl);

  const allSubs = result.all_submissions || [];
  const roundNum = result.round_number ?? ctx.roundNumber ?? 1;
  const totalRounds = result.total_rounds ?? ctx.totalRounds ?? ctx.session?.rounds?.length ?? 5;
  const totalBasePoints = result.total_base_points ?? (totalRounds * (result.base_points ?? 20.0));
  const remainingScore = Number(result.round_score ?? totalBasePoints);
  const youSub = allSubs.find((s) => s.is_you);
  const thisRoundPenalty = youSub ? Number(youSub.penalty ?? 0) : Number(result.penalty ?? 0);
  const rankLabel = result.is_valid && result.rank ? `#${result.rank}` : (youSub && youSub.rank ? `#${youSub.rank}` : '—');
  const bestRank = allSubs.reduce((min, s) => (s.rank && s.rank < min ? s.rank : min), Infinity);

  container.innerHTML = `
    <div class="kd-rv-root">
      <div class="kd-rv-eyebrow">Sub-Round ${roundNum} / ${totalRounds}</div>
      <div class="kd-rv-title">Computation Result</div>
      <div class="kd-rv-beam-wrap"><div class="kd-rv-beam" id="kd-rv-beam"></div></div>
      <div class="kd-rv-teams" id="kd-rv-teams"></div>
      <div class="kd-rv-calc" id="kd-rv-calc">
        <div class="kd-rv-calc-label">Average × 0.8</div>
        <div class="kd-rv-formula" id="kd-rv-formula">&nbsp;</div>
        <div class="kd-rv-target-row">
          <span class="kd-rv-target-label">Target</span>
          <span class="kd-rv-target" id="kd-rv-target">—</span>
        </div>
      </div>
      <div class="kd-rv-points" id="kd-rv-points">
        <div class="kd-rv-points-label">Points Remaining</div>
        <div class="kd-rv-points-num" id="kd-rv-points-num">${totalBasePoints}</div>
        <div class="kd-rv-points-sub" id="kd-rv-points-sub"></div>
      </div>
      <div class="kd-rv-footer" id="kd-rv-footer">
        <span class="kd-rv-footer-txt">Next in <strong id="kd-rv-timer">15s</strong></span>
        <button class="kd-rv-next-btn" id="kd-rv-next-btn">Continue →</button>
      </div>
    </div>
  `;

  const teamsEl = container.querySelector('#kd-rv-teams');
  const beamEl = container.querySelector('#kd-rv-beam');
  const calcEl = container.querySelector('#kd-rv-calc');
  const formulaEl = container.querySelector('#kd-rv-formula');
  const targetEl = container.querySelector('#kd-rv-target');
  const pointsEl = container.querySelector('#kd-rv-points');
  const pointsNumEl = container.querySelector('#kd-rv-points-num');
  const pointsSubEl = container.querySelector('#kd-rv-points-sub');
  const footerEl = container.querySelector('#kd-rv-footer');
  const timerEl = container.querySelector('#kd-rv-timer');
  const nextBtn = container.querySelector('#kd-rv-next-btn');

  // Footer/timer is live from frame one — the caller's 15s countdown starts
  // now, in parallel with everything below, instead of after it.
  footerEl.classList.add('kd-rv-in');
  if (typeof onDone === 'function') onDone({ timerEl, nextBtn });

  const isLive = () => container.isConnected;

  // ---- build one card per team (numbers hidden for now) ----
  const cardEls = allSubs.map((s) => {
    const card = document.createElement('div');
    card.className = 'kd-rv-card' + (s.is_you ? ' kd-rv-you' : '');
    card.innerHTML = `
      <div class="kd-rv-icon">${kdInitials(s.team_code)}</div>
      <div class="kd-rv-name">${s.team_code}</div>
      <div class="kd-rv-number">—</div>
      <span class="kd-rv-win-flag">WIN</span>
      <div class="kd-rv-deduct">-${(Number(s.penalty ?? 0)).toFixed(1)}</div>
    `;
    teamsEl.appendChild(card);
    return { el: card, sub: s };
  });
  const n = cardEls.length || 1;

  // Whole choreography below is budgeted to land around ~10-11s in for a
  // typical room, regardless of team count — stagger gaps shrink as n grows
  // instead of the sequence just running longer — leaving a few seconds of
  // buffer before the 15s auto-advance so it never feels stacked on top.

  // 1) Teams appear, staggered (budget ~1300ms total spread across all cards)
  const cardStep = kdStagger(n, 1300, 40, 170);
  cardEls.forEach(({ el }, i) => { el.style.transitionDelay = `${i * cardStep}ms`; });
  await kdDelay(80);
  cardEls.forEach(({ el }) => el.classList.add('kd-rv-in'));
  if (!isLive()) return;
  await kdDelay(n * cardStep + 550);
  if (!isLive()) return;

  // 2) Numbers count up, staggered (budget ~900ms total)
  const numStep = kdStagger(n, 900, 30, 130);
  beamEl.classList.add('kd-rv-weighing');
  await Promise.all(cardEls.map(({ el, sub }, i) => (async () => {
    await kdDelay(i * numStep);
    const numEl = el.querySelector('.kd-rv-number');
    await kdCountUp(numEl, sub.submitted_number, 700);
    numEl.classList.add('kd-rv-pop');
  })()));
  if (!isLive()) return;
  await kdDelay(350);

  // 3) Average x 0.8 calculation
  const validSubs = allSubs.filter((s) => s.is_valid);
  const termStep = kdStagger(validSubs.length, 800, 40, 150);
  formulaEl.textContent = '';
  for (let i = 0; i < validSubs.length; i++) {
    formulaEl.textContent += (i === 0 ? '' : ' + ') + kdNum(validSubs[i].submitted_number);
    await kdDelay(termStep);
  }
  if (!isLive()) return;
  await kdDelay(300);
  formulaEl.textContent += ` = ${kdNum(result.average_value)}  →  ×0.8`;
  calcEl.classList.add('kd-rv-in');
  await kdDelay(850);
  if (!isLive()) return;
  targetEl.textContent = kdNum(result.target_value);
  targetEl.classList.add('kd-rv-in', 'kd-rv-pop');
  await kdDelay(850);
  if (!isLive()) return;

  // 4) Winner reveal — beam settles, winning card(s) light up
  beamEl.classList.remove('kd-rv-weighing');
  beamEl.classList.add('kd-rv-settled');
  cardEls.forEach(({ el, sub }) => {
    if (sub.rank === bestRank && sub.is_valid) el.classList.add('kd-rv-winner');
    else el.classList.add('kd-rv-dim');
  });
  await kdDelay(1100);
  if (!isLive()) return;
  cardEls.forEach(({ el }) => el.classList.remove('kd-rv-dim'));

  // 5) Deductions drop in for every team (budget ~500ms total)
  const dedStep = kdStagger(n, 500, 25, 90);
  cardEls.forEach(({ el }, i) => {
    const d = el.querySelector('.kd-rv-deduct');
    setTimeout(() => { if (isLive()) d.classList.add('kd-rv-in'); }, i * dedStep);
  });
  await kdDelay(n * dedStep + 500);
  if (!isLive()) return;

  // 6) Your remaining points
  pointsEl.classList.add('kd-rv-in');
  pointsSubEl.textContent = `This round: -${thisRoundPenalty.toFixed(1)} pts  ·  Rank: ${rankLabel}`;
  const prevRemaining = Math.min(totalBasePoints, remainingScore + thisRoundPenalty);
  await kdCountUp(pointsNumEl, prevRemaining, 1);
  await kdCountUp(pointsNumEl, remainingScore, 900);
  // Sequence typically lands around 10-11s in, leaving a real buffer before
  // the 15s auto-advance so the final numbers are readable, not rushed.
}

function kdNum(n) {
  if (n === null || n === undefined) return '—';
  const v = Number(n);
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}