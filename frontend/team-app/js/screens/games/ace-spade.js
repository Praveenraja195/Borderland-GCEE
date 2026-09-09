import { api } from '../../../../shared/js/api.js?v=v51_typewriter_scoreboard';
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

// The shell decides when the round has started using the server-adjusted
// clock (see startCountdown in shared/js/ui.js), so the in-round timeline
// runs on the same clock — otherwise a device whose clock is off by a
// second would see the 3-2-1 hit GO! and the first deal start late/early.
function serverNow() {
  return typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now();
}

const SUITS = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];
const RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10'];
const SUIT_SYMBOLS = { SPADE: '♠', HEART: '♥', DIAMOND: '♦', CLUB: '♣' };
const RED_SUITS = new Set(['HEART', 'DIAMOND']);

const MEMORIZE_COUNT = 8;
const DECOY_COUNT = 4; // 8 + 4 = 12 cards in the recall grid, a clean 4×3
const MEMORIZE_DURATION = 30; // seconds to memorize the 8 cards + order
const SELECT_DURATION = 40;   // seconds to tap them back in order
// Each phase is preceded by a shuffle-and-deal animation with its own time
// slot, so the memorize/select clocks only run once the cards are actually
// in place. MUST match settings.ace_spade_deal_seconds on the server —
// the round deadline is memorize + select + 2 × deal.
const DEAL_DURATION = 8;

const REDUCED_MOTION = typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Deterministic PRNG seeded from the round id, so a page reload regenerates
// the exact same deck + layout instead of losing/reshuffling it — same
// technique mindmaze.js uses for its lit-tile set.
function seededRng(seed) {
  let h = 0;
  const str = String(seed || 'ace_spade_default');
  for (let i = 0; i < str.length; i++) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return function next() {
    h = (Math.imul(1664525, h) + 1013904223) | 0;
    return (h >>> 0) / 4294967296;
  };
}

function shuffled(arr, rng) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function buildDeck() {
  const deck = [];
  for (const s of SUITS) {
    for (const r of RANKS) {
      deck.push({ id: `${s}_${r}`, suit: s, rank: r });
    }
  }
  return deck;
}

// memorize: the 8 cards, IN THE ORDER they must be recalled.
// decoys: the 3 extra cards mixed in for the recall phase.
// recallPool: all 11 cards (memorize + decoys), in the shuffled order they
// are displayed face-up during the selection phase.
function getRoundCards(seedKey) {
  const rng = seededRng(seedKey);
  const deck = shuffled(buildDeck(), rng);
  const memorize = deck.slice(0, MEMORIZE_COUNT);
  const decoys = deck.slice(MEMORIZE_COUNT, MEMORIZE_COUNT + DECOY_COUNT);
  const recallPool = shuffled(memorize.concat(decoys), rng);
  return { memorize, decoys, recallPool };
}

export function renderAceSpade(root, navigate) {
  return renderGameScreen(root, navigate, {
    gameCode: 'ACE_SPADE',
    apiGameCode: 'ace-spade',
    renderActive(container, ctx, { navigate, reload }) {
      mountRound(container, ctx, reload);
    },
  });
}

function roundBadge(ctx) {
  if (!ctx.roundNumber) return '';
  const label = ctx.totalRounds ? `Round ${ctx.roundNumber} / ${ctx.totalRounds}` : `Round ${ctx.roundNumber}`;
  return `<div class="status-note" style="text-align:center;font-weight:700;color:var(--bl-gray);padding-bottom:4px;">${label}</div>`;
}

// Real playing-card layout: a rank+suit index in the top-left and a
// mirrored (rotated) one in the bottom-right, plus a big suit pip
// centered — the standard card-face convention, not just a floating
// symbol+number. The face and a patterned back sit on a 3D-flippable
// inner wrapper so the pile can be dealt face-down and turned over.
function cardInnerHTML(card) {
  const isRed = RED_SUITS.has(card.suit);
  const symbol = SUIT_SYMBOLS[card.suit] || '?';
  const colorClass = isRed ? 'as-red' : 'as-black';
  return `
    <div class="as-card-inner">
      <div class="as-card-face">
        <div class="as-card-corner as-card-corner-tl ${colorClass}">
          <span class="as-corner-rank">${card.rank}</span>
          <span class="as-corner-suit">${symbol}</span>
        </div>
        <div class="as-card-center-suit ${colorClass}">${symbol}</div>
        <div class="as-card-corner as-card-corner-br ${colorClass}">
          <span class="as-corner-rank">${card.rank}</span>
          <span class="as-corner-suit">${symbol}</span>
        </div>
      </div>
      <div class="as-card-back"></div>
    </div>
  `;
}

let _stylesInjected = false;
function injectAceSpadeStyles() {
  if (_stylesInjected) return;
  _stylesInjected = true;
  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .as-arena-card { max-width: 460px; margin: 0 auto; display: flex; flex-direction: column; }
    .as-card-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      width: 100%;
      box-sizing: border-box;
    }
    .as-memo-cell {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 5px;
    }
    /* Outer element = position (grid slot, or an offset onto the pile via
       --sx/--sy/--sr). Inner element = 3D flip. Keeping the two on separate
       elements means dealing and flipping never fight over 'transform'. */
    .as-card {
      position: relative;
      aspect-ratio: 3 / 4;
      width: 100%;
      border: 0;
      background: transparent;
      padding: 0;
      cursor: pointer;
      user-select: none;
      -webkit-tap-highlight-color: transparent;
      perspective: 700px;
      z-index: 1;
      transform: translate(var(--sx, 0px), var(--sy, 0px)) rotate(var(--sr, 0deg));
      transition: transform 0.55s cubic-bezier(0.22, 0.9, 0.3, 1), opacity 0.3s ease;
    }
    .as-card:active {
      transform: translate(var(--sx, 0px), var(--sy, 0px)) rotate(var(--sr, 0deg)) scale(0.96);
    }
    .as-card-grid.as-no-transition .as-card { transition: none !important; }
    .as-card-grid.as-shuffling .as-card {
      transition-duration: 0.17s;
      transition-timing-function: ease-in-out;
    }
    .as-card.as-arriving { opacity: 0; }
    .as-card-inner {
      position: absolute;
      inset: 0;
      border-radius: 9px;
      transform-style: preserve-3d;
      /* The turn-over after a deal is deliberately unhurried so the
         reveal reads as a flip rather than a blink. */
      transition: transform 0.9s cubic-bezier(0.35, 0.1, 0.25, 1);
    }
    .as-card.as-face-down .as-card-inner { transform: rotateY(180deg); }
    .as-card-face, .as-card-back {
      position: absolute;
      inset: 0;
      border-radius: 9px;
      overflow: hidden;
      backface-visibility: hidden;
      -webkit-backface-visibility: hidden;
      border: 1px solid #d6dbe3;
      box-shadow: 0 2px 5px rgba(15, 23, 42, 0.14);
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .as-card-face {
      background: linear-gradient(180deg, #ffffff 0%, #fbfbfa 100%);
    }
    /* Card back: the shared red crosshatch back texture, as-is. Asset path
       follows the shell's convention (resolved against the team-app
       document → /shared/...). */
    .as-card-back {
      transform: rotateY(180deg);
      border-color: #9f1239;
      background: #b91c1c url('../../../../shared/assets/card_backside.webp') center / cover no-repeat;
      box-shadow: 0 2px 5px rgba(15, 23, 42, 0.22);
    }
    .as-card.as-picked .as-card-face {
      border-color: var(--bl-red);
      box-shadow: 0 0 0 2px var(--bl-red), 0 3px 8px rgba(229, 57, 53, 0.25);
    }
    .as-card-corner {
      position: absolute;
      z-index: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      line-height: 1;
    }
    .as-card-corner-tl { top: 7%; left: 9%; }
    .as-card-corner-br { bottom: 7%; right: 9%; transform: rotate(180deg); }
    .as-corner-rank { font-size: 0.82rem; font-weight: 800; }
    .as-corner-suit { font-size: 0.68rem; margin-top: 1px; }
    .as-card-center-suit {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 0;
      font-size: 2rem;
      line-height: 1;
    }
    .as-card-corner.as-red, .as-card-center-suit.as-red { color: #d5262b; }
    .as-card-corner.as-black, .as-card-center-suit.as-black { color: #0f172a; }
    .as-card-pick-badge {
      position: absolute;
      top: -6px;
      right: -6px;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--bl-red);
      color: #fff;
      font-size: 0.75rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.25);
      z-index: 2;
    }
    /* Order badge shown below each card during the memorize phase, so the
       recall order is obvious at a glance instead of relying on reading
       position alone. */
    .as-memo-order {
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: var(--bl-ink, #0f172a);
      color: #fff;
      font-weight: 800;
      font-size: 0.78rem;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 1px 3px rgba(0,0,0,0.25);
      flex-shrink: 0;
      transition: opacity 0.3s ease, transform 0.3s ease;
    }
    .as-memo-order.as-hidden { opacity: 0; transform: translateY(-4px); }
  `;
  document.head.appendChild(styleEl);
}

function renderScoreReveal(container, ctx, { score, correctPicks, wrongPicks }, onDone, initialSecs = 5) {
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
            Correct: <strong style="color: #166534;">${correctPicks ?? 0} / 8</strong>
          </span>
          <span style="background: #f1f5f9; padding: 4px 12px; border-radius: 6px; color: #334155;">
            Wrong: <strong style="color: #991b1b;">${wrongPicks ?? 0}</strong>
          </span>
        </div>
      </div>

      <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; text-align: center;">
        <span style="font-size: 0.88rem; color: #64748b; font-weight: 600;">
          Next screen in <strong id="as-reveal-timer" style="color: var(--bl-red); font-size: 1.1rem;">${remaining}s</strong>...
        </span>
      </div>
    </div>
  `;

  const timerEl = container.querySelector('#as-reveal-timer');

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

function renderWaitingScreen(container, ctx, { score, correctPicks, wrongPicks }) {
  const currentSubScore = score !== undefined && score !== null ? Number(score) : 0;

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
      ${ctx.submitted && (score !== null && score !== undefined) ? `
      <div style="background: #ffffff; border: 1px solid var(--bl-border); border-radius: 10px; padding: 14px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
          <span style="font-size: 0.9rem; font-weight: 700; color: #1e293b;">
            Sub-Round ${ctx.roundNumber || ''} Result: <strong style="color: var(--bl-red); font-family: var(--font-mono);">+${formatScore(currentSubScore)} pts</strong>
          </span>
          <span style="font-size: 0.78rem; color: var(--bl-gray);">Correct: ${correctPicks ?? 0} / 8 · Wrong: ${wrongPicks ?? 0}</span>
        </div>
        ${demoNoteHTML(ctx.isDemo)}
        <div style="border-top: 1px dashed #e2e8f0; padding-top: 10px; margin-top: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 6px;">
          <div style="font-size: 0.85rem; font-weight: 700; color: #1e293b;">
            Cumulative Ace of Spades Score: <span style="font-family: var(--font-mono); color: var(--bl-red); font-size: 1.1rem;">${formatScore(totalScore)} pts</span>
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

// Exported so the round can be mounted standalone (e.g. a visual harness)
// without going through the shell's session polling.
export function mountRound(container, ctx, reload) {
  injectAceSpadeStyles();

  if (ctx.submitted || ctx.allClosed) {
    let revealData = {
      score: ctx.score,
      correctPicks: ctx.correctPicks,
      wrongPicks: ctx.wrongPicks,
    };
    const savedStr = localStorage.getItem(`bl_as_reveal_${ctx.roundId}`);
    if (savedStr) {
      try {
        revealData = JSON.parse(savedStr);
      } catch (_) { }
    }

    renderWaitingScreen(container, ctx, revealData);
    return;
  }

  try {
    localStorage.removeItem(`bl_as_reveal_${ctx.roundId}`);
  } catch (_) { }

  if (!ctx.startTime) {
    try {
      localStorage.removeItem(`bl_as_state_${ctx.roundId}`);
    } catch (_) { }
    renderWaitingScreen(container, ctx, { score: null, correctPicks: null, wrongPicks: null });
    return;
  }

  const serverStartTs = new Date(ctx.startTime).getTime();

  let stateData = null;
  const savedStateStr = localStorage.getItem(`bl_as_state_${ctx.roundId}`);
  if (savedStateStr) {
    try {
      stateData = JSON.parse(savedStateStr);
    } catch (_) { }
  }

  if (stateData && stateData.startTs && Math.abs(Number(stateData.startTs) - serverStartTs) > 3000) {
    stateData = null;
    try { localStorage.removeItem(`bl_as_state_${ctx.roundId}`); } catch (_) { }
  }

  const seedKey = ctx.roundId ? String(ctx.roundId) : (ctx.sessionId ? `${ctx.sessionId}_${ctx.roundNumber}` : `round_${ctx.roundNumber || 1}`);
  const { memorize, decoys, recallPool } = getRoundCards(seedKey);
  const decoyIds = new Set(decoys.map((c) => c.id));

  // path: ordered array of card ids the player has tapped, in tap order.
  let path = [];
  let moves = 0;
  let startTs = serverStartTs;

  if (stateData) {
    if (Array.isArray(stateData.path)) {
      path = stateData.path.slice(0, MEMORIZE_COUNT);
    }
    moves = Number(stateData.moves || 0);
  } else {
    saveStateToStorage();
  }

  function saveStateToStorage() {
    localStorage.setItem(`bl_as_state_${ctx.roundId}`, JSON.stringify({
      startTs,
      path,
      moves,
    }));
  }

  function clearStateFromStorage() {
    localStorage.removeItem(`bl_as_state_${ctx.roundId}`);
  }

  // Round timeline, in seconds from the server start_time. Every phase is
  // derived from elapsed time on each tick (rather than decremented), so a
  // reload lands in the right phase and the clocks never drift.
  //
  //   [0, DEAL)                 deal1     pile → shuffle → deal 8 cards
  //   [DEAL, DEAL+MEM)          display   memorize, 30s clock runs
  //   [DEAL+MEM, 2·DEAL+MEM)    deal2     gather → +3 cards → shuffle → deal 11
  //   [2·DEAL+MEM, …+SEL)       selection tap back in order, 40s clock runs
  const T_DEAL1_END = DEAL_DURATION;
  const T_MEM_END = T_DEAL1_END + MEMORIZE_DURATION;
  const T_DEAL2_END = T_MEM_END + DEAL_DURATION;
  const T_SEL_END = T_DEAL2_END + SELECT_DURATION;

  function phaseAt(elapsed) {
    if (elapsed < T_DEAL1_END) return { phase: 'deal1', timeLeft: MEMORIZE_DURATION };
    if (elapsed < T_MEM_END) return { phase: 'display', timeLeft: T_MEM_END - elapsed };
    if (elapsed < T_DEAL2_END) return { phase: 'deal2', timeLeft: SELECT_DURATION };
    if (elapsed < T_SEL_END) return { phase: 'selection', timeLeft: T_SEL_END - elapsed };
    return { phase: 'selection', timeLeft: 0 };
  }

  const initial = phaseAt(Math.max(0, (serverNow() - startTs) / 1000));

  const rounds = ctx.session?.rounds || [];
  let totalScoreSoFar = 0;
  rounds.forEach((r) => {
    if (r.round_number < (ctx.roundNumber || 1) && r.submitted && r.score !== undefined && r.score !== null) {
      totalScoreSoFar += Number(r.score);
    }
  });

  const state = {
    phase: null, // set by enterPhase()
    path,
    moves,
    startedAt: startTs + (T_DEAL2_END * 1000), // selection phase start
    submitting: false,
    timeLeft: initial.timeLeft,
  };

  container.innerHTML = `
    <div class="as-arena-card">
      <div style="min-height: 54px; display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 8px;">
        <div>
          ${roundBadge(ctx)}
          <div class="countdown-wrap" style="padding: 0; flex: none; align-items: flex-start;">
            <div class="countdown-face" id="as-timer" style="font-size: 2.2rem; line-height: 1; font-family: var(--font-mono); font-weight: 800;">00:30</div>
            <div class="countdown-label" id="as-phase-note" style="min-height: 16px; line-height: 16px; font-size: 0.76rem; font-weight: 700; color: var(--bl-red); margin-top: 2px;"></div>
          </div>
        </div>

        <div style="background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; padding: 4px 10px; text-align: right; box-shadow: 0 1px 3px rgba(0,0,0,0.06); min-width: 84px;">
          <div style="font-size: 0.68rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em;">Total Score</div>
          <div style="font-family: var(--font-mono); font-size: 1.1rem; font-weight: 800; color: var(--bl-red); line-height: 1.1;">
            ${formatScore(totalScoreSoFar)} <span style="font-size: 0.72rem; font-weight: 700;">pts</span>
          </div>
        </div>
      </div>

      <div class="as-card-grid" id="as-grid" style="margin-top: 14px;"></div>

      <div class="as-stat-row" style="height: 24px; display: flex; justify-content: space-between; align-items: center; padding: 2px 4px; font-size: 0.82rem; font-weight: 600; color: var(--bl-gray); margin-top: 8px;">
        <span id="as-picked-count" style="color: var(--bl-ink);">Selected: ${state.path.length} / ${MEMORIZE_COUNT}</span>
        <span id="as-moves">Moves: ${state.moves}</span>
      </div>

      <div class="status-note" style="text-align:center; font-size:0.78rem; color:var(--bl-red); margin-top:8px; font-weight:600; height: 18px; line-height: 18px;">
        Auto-submits when timer expires / 制限時間終了時に自動送信されます
      </div>
    </div>
  `;

  const grid = container.querySelector('#as-grid');
  const timerFace = container.querySelector('#as-timer');
  const phaseNote = container.querySelector('#as-phase-note');
  const movesEl = container.querySelector('#as-moves');
  const pickedCountEl = container.querySelector('#as-picked-count');

  function updatePickedCount() {
    if (pickedCountEl) pickedCountEl.textContent = `Selected: ${state.path.length} / ${MEMORIZE_COUNT}`;
  }

  function makeCardEl(card, { asButton }) {
    const el = document.createElement(asButton ? 'button' : 'div');
    if (asButton) el.type = 'button';
    el.className = 'as-card';
    el.dataset.cardId = card.id;
    el.innerHTML = cardInnerHTML(card);
    return el;
  }

  // Returns the card elements so the deal animation can drive them.
  function renderMemorizeGrid({ faceDown = false } = {}) {
    grid.innerHTML = '';
    const cards = [];
    memorize.forEach((card, i) => {
      const cellWrap = document.createElement('div');
      cellWrap.className = 'as-memo-cell';

      const cell = makeCardEl(card, { asButton: false });
      cell.style.cursor = 'default';
      if (faceDown) cell.classList.add('as-face-down');

      // Order badge — shows the exact position (1, 2, 3…) each card must
      // be recalled in, since the grid's reading order alone isn't an
      // obvious enough cue.
      const orderBadge = document.createElement('div');
      orderBadge.className = 'as-memo-order';
      if (faceDown) orderBadge.classList.add('as-hidden');
      orderBadge.textContent = String(i + 1);

      cellWrap.appendChild(cell);
      cellWrap.appendChild(orderBadge);
      grid.appendChild(cellWrap);
      cards.push(cell);
    });
    return cards;
  }

  function renderRecallGrid({ faceDown = false } = {}) {
    grid.innerHTML = '';
    const cells = [];
    recallPool.forEach((card) => {
      const cell = makeCardEl(card, { asButton: true });
      if (faceDown) cell.classList.add('as-face-down');
      grid.appendChild(cell);
      cells.push(cell);
    });

    function refreshBadges() {
      cells.forEach((cell) => {
        const existing = cell.querySelector('.as-card-pick-badge');
        if (existing) existing.remove();
        const idx = state.path.indexOf(cell.dataset.cardId);
        if (idx >= 0) {
          cell.classList.add('as-picked');
          const badge = document.createElement('span');
          badge.className = 'as-card-pick-badge';
          badge.textContent = String(idx + 1);
          cell.appendChild(badge);
        } else {
          cell.classList.remove('as-picked');
        }
      });
    }
    refreshBadges();

    cells.forEach((cell) => {
      cell.onclick = () => {
        if (state.phase !== 'selection') return;
        const cardId = cell.dataset.cardId;
        const idx = state.path.indexOf(cardId);
        if (idx >= 0) {
          // Deselect: remove this pick, shift later picks down so the
          // numbering stays contiguous and the player can pick up where
          // they left off.
          state.path.splice(idx, 1);
        } else {
          if (state.path.length >= MEMORIZE_COUNT) {
            toast(`You can only select ${MEMORIZE_COUNT} cards — deselect one first.`, { error: false });
            return;
          }
          state.path.push(cardId);
        }
        state.moves += 1;
        if (movesEl) movesEl.textContent = `Moves: ${state.moves}`;
        updatePickedCount();
        refreshBadges();
        saveStateToStorage();
      };
    });
    return cells;
  }

  // ── Deal animations ──────────────────────────────────────────────────
  // Cards are always rendered straight into their real grid slots; the
  // "pile" is just each card translated (via --sx/--sy/--sr) onto the
  // grid's centre. Dealing = clearing those offsets and letting the CSS
  // transition carry each card home. Every sequence checks `animToken` so
  // a phase change (or a reload racing the clock) abandons it cleanly.
  let animToken = 0;
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => resolve()));

  // The shell inserts this container and calls renderActive in the same
  // tick, so the grid may not have a laid-out width yet. Pile offsets are
  // measured from real geometry, so wait (briefly) for layout to settle;
  // returns false if it never does, in which case the caller skips the
  // animation rather than dealing from a 0×0 pile.
  async function waitForLayout() {
    for (let i = 0; i < 12; i++) {
      if (grid.getBoundingClientRect().width > 0) return true;
      await nextFrame();
    }
    return grid.getBoundingClientRect().width > 0;
  }

  function pileOffsets(cards) {
    const g = grid.getBoundingClientRect();
    const cx = g.left + g.width / 2;
    const cy = g.top + g.height / 2;
    return cards.map((card, i) => {
      const r = card.getBoundingClientRect();
      return {
        dx: cx - (r.left + r.width / 2),
        dy: cy - (r.top + r.height / 2) - i * 0.7,
        rot: ((i * 37) % 9) - 4,
      };
    });
  }

  function placeAt(card, o, zIndex) {
    card.style.setProperty('--sx', `${o.dx}px`);
    card.style.setProperty('--sy', `${o.dy}px`);
    card.style.setProperty('--sr', `${o.rot}deg`);
    if (zIndex !== undefined) card.style.zIndex = String(zIndex);
  }

  function placeHome(card) {
    card.style.setProperty('--sx', '0px');
    card.style.setProperty('--sy', '0px');
    card.style.setProperty('--sr', '0deg');
    card.style.zIndex = '';
  }

  // Move cards without animating (measure → offset → reflow in one frame,
  // so nothing paints in the grid slot first).
  function snapTo(cards, offsets) {
    grid.classList.add('as-no-transition');
    cards.forEach((c, i) => placeAt(c, offsets[i], 10 + i));
    void grid.offsetHeight;
    grid.classList.remove('as-no-transition');
  }

  async function shufflePile(cards, offsets, token, cuts = 4) {
    const cardW = cards[0] ? cards[0].getBoundingClientRect().width : 60;
    grid.classList.add('as-shuffling');
    for (let m = 0; m < cuts; m++) {
      if (token !== animToken) break;
      const dir = m % 2 === 0 ? 1 : -1;
      const movers = cards.filter((_, i) => (i + m) % 2 === 0);
      movers.forEach((c) => {
        const o = offsets[cards.indexOf(c)];
        placeAt(c, { ...o, dx: o.dx + dir * cardW * 0.65, rot: o.rot + dir * 6 }, 40);
      });
      await wait(170);
      movers.forEach((c) => placeAt(c, offsets[cards.indexOf(c)], 10 + cards.indexOf(c)));
      await wait(190);
    }
    grid.classList.remove('as-shuffling');
  }

  // Deal each card home with a stagger, let them settle, then turn them
  // over one after another. The flip itself is 0.9s (see .as-card-inner),
  // so the stagger is wide enough that the turn reads as a wave rather
  // than everything flipping at once.
  const FLIP_STAGGER_MS = 110;
  const FLIP_MS = 900;

  async function dealOut(cards, token, { stagger = 80 } = {}) {
    cards.forEach((c, i) => {
      setTimeout(() => { if (token === animToken) placeHome(c); }, i * stagger);
    });
    await wait(cards.length * stagger + 600);
    if (token !== animToken) return;
    cards.forEach((c, i) => {
      setTimeout(() => { if (token === animToken) c.classList.remove('as-face-down'); }, i * FLIP_STAGGER_MS);
    });
    await wait(cards.length * FLIP_STAGGER_MS + FLIP_MS);
  }

  function setOrderBadgesHidden(hidden) {
    grid.querySelectorAll('.as-memo-order').forEach((b) => b.classList.toggle('as-hidden', hidden));
  }

  // Phase 1 intro: pile appears at the centre, gets shuffled, deals out.
  async function runDeal1(token) {
    const cards = renderMemorizeGrid({ faceDown: true });
    const canAnimate = !REDUCED_MOTION && await waitForLayout();
    if (token !== animToken) return;
    if (!canAnimate) {
      cards.forEach((c) => c.classList.remove('as-face-down'));
      setOrderBadgesHidden(false);
      return;
    }
    const offsets = pileOffsets(cards);
    cards.forEach((c) => c.classList.add('as-arriving'));
    snapTo(cards, offsets);
    void grid.offsetHeight;
    cards.forEach((c) => c.classList.remove('as-arriving'));
    await wait(380);
    if (token !== animToken) return;
    await shufflePile(cards, offsets, token, 6);
    if (token !== animToken) return;
    await dealOut(cards, token, { stagger: 90 });
    if (token !== animToken) return;
    setOrderBadgesHidden(false);
  }

  // Phase 2 intro: the 8 memorised cards fold back into a pile, 3 new
  // cards fly in from outside the grid, everything is shuffled and dealt
  // out again face-down → face-up.
  async function runDeal2(token) {
    const oldCards = Array.from(grid.querySelectorAll('.as-card'));
    const canAnimate = !REDUCED_MOTION && await waitForLayout();
    if (token !== animToken) return;
    if (canAnimate && oldCards.length) {
      setOrderBadgesHidden(true);
      const gather = pileOffsets(oldCards);
      oldCards.forEach((c, i) => {
        setTimeout(() => {
          if (token !== animToken) return;
          c.classList.add('as-face-down');
          placeAt(c, gather[i], 10 + i);
        }, (oldCards.length - 1 - i) * 45);
      });
      await wait(oldCards.length * 45 + 560);
      if (token !== animToken) return;
    }

    const cards = renderRecallGrid({ faceDown: true });
    if (!canAnimate) {
      cards.forEach((c) => c.classList.remove('as-face-down'));
      return;
    }

    const offsets = pileOffsets(cards);
    const g = grid.getBoundingClientRect();
    const cardH = cards[0] ? cards[0].getBoundingClientRect().height : 80;
    const newIdx = [];
    cards.forEach((c, i) => { if (decoyIds.has(c.dataset.cardId)) newIdx.push(i); });

    // Pile is already there (same look as the gathered pile); the 3 new
    // cards start above-right of the grid, invisible.
    snapTo(cards, offsets.map((o, i) => (
      newIdx.includes(i) ? { dx: o.dx + g.width * 0.45, dy: o.dy - cardH * 1.15, rot: 28 } : o
    )));
    newIdx.forEach((i) => cards[i].classList.add('as-arriving'));
    void grid.offsetHeight;

    newIdx.forEach((i, k) => {
      setTimeout(() => {
        if (token !== animToken) return;
        cards[i].classList.remove('as-arriving');
        placeAt(cards[i], offsets[i], 30 + k);
      }, 120 + k * 170);
    });
    await wait(120 + newIdx.length * 170 + 520);
    if (token !== animToken) return;
    await shufflePile(cards, offsets, token, 4);
    if (token !== animToken) return;
    await dealOut(cards, token, { stagger: 70 });
  }

  // ── Phase machine ────────────────────────────────────────────────────
  const PHASE_NOTES = {
    deal1: { text: 'Shuffling & dealing the cards…', color: 'var(--bl-gray)' },
    display: { text: 'Phase 1: Memorize the cards & order…', color: 'var(--bl-red)' },
    deal2: { text: `Adding ${DECOY_COUNT} new cards & re-dealing…`, color: 'var(--bl-gray)' },
    selection: { text: 'Phase 2: Tap cards back in order…', color: '#166534' },
  };

  function enterPhase(phase) {
    state.phase = phase;
    animToken += 1;
    const token = animToken;
    const note = PHASE_NOTES[phase];
    if (phaseNote && note) {
      phaseNote.textContent = note.text;
      phaseNote.style.color = note.color;
    }
    if (phase === 'deal1') {
      runDeal1(token);
    } else if (phase === 'display') {
      renderMemorizeGrid();
    } else if (phase === 'deal2') {
      runDeal2(token);
    } else if (phase === 'selection') {
      renderRecallGrid();
    }
  }

  function updateTimerDisplay() {
    const secsStr = String(Math.max(Math.ceil(state.timeLeft), 0)).padStart(2, '0');
    timerFace.textContent = `00:${secsStr}`;
  }

  enterPhase(initial.phase);
  updateTimerDisplay();

  const timerInterval = setInterval(() => {
    if (!container.isConnected || state.phase === 'submitted') {
      clearInterval(timerInterval);
      return;
    }

    const p = phaseAt(Math.max(0, (serverNow() - startTs) / 1000));
    if (p.phase !== state.phase) enterPhase(p.phase);
    state.timeLeft = p.timeLeft;
    updateTimerDisplay();

    if (p.phase === 'selection' && p.timeLeft <= 0) {
      clearInterval(timerInterval);
      autoSubmitResult();
    }
  }, 250);

  async function submitResult(isAuto = false) {
    if (state.submitting || state.phase === 'submitted') return;
    state.submitting = true;

    let correctPicks = 0;
    let wrongPicks = 0;
    state.path.forEach((cardId, i) => {
      const expected = memorize[i];
      if (expected && expected.id === cardId) {
        correctPicks += 1;
      } else {
        wrongPicks += 1;
      }
    });
    const moves = Math.max(state.moves, state.path.length);
    const completionTimeSeconds = state.startedAt ? Math.max(0, (Date.now() - state.startedAt) / 1000) : 0;

    try {
      const res = await gameApi(ctx).aceSpadeSubmit(ctx.roundId, {
        moves,
        wrong_picks: wrongPicks,
        correct_picks: correctPicks,
        completion_time_seconds: completionTimeSeconds,
      });
      clearStateFromStorage();
      clearInterval(timerInterval);
      state.phase = 'submitted';

      const revealData = {
        score: res.round_score,
        correctPicks: res.correct_picks,
        wrongPicks: res.wrong_picks,
        submittedAt: Date.now(),
      };
      localStorage.setItem(`bl_as_reveal_${ctx.roundId}`, JSON.stringify(revealData));

      renderScoreReveal(container, ctx, revealData, () => {
        renderWaitingScreen(container, ctx, revealData, reload);
      }, 5);
    } catch (err) {
      if (err.status === 409) {
        clearStateFromStorage();
        clearInterval(timerInterval);
        state.phase = 'submitted';

        const fallbackScore = Math.max(0, (correctPicks * 2.0) - (wrongPicks * 0.5));
        const revealData = {
          score: ctx.score !== undefined && ctx.score !== null ? ctx.score : fallbackScore,
          correctPicks: ctx.correctPicks !== undefined && ctx.correctPicks !== null ? ctx.correctPicks : correctPicks,
          wrongPicks: ctx.wrongPicks !== undefined && ctx.wrongPicks !== null ? ctx.wrongPicks : wrongPicks,
          submittedAt: Date.now(),
        };
        localStorage.setItem(`bl_as_reveal_${ctx.roundId}`, JSON.stringify(revealData));

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
