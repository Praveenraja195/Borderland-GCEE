import { api } from '../../../../shared/js/api.js';
import { HEADERS, GAMES, STATUS, INSTRUCTIONS, DEMO } from '../../../../shared/js/copy.js';
import { startCountdown, formatCountdown } from '../../../../shared/js/ui.js';
import { getRoundContext, setRoundContext, renderRoundContextForm, clearRoundContext } from '../../round-context.js';
import { LiveChannel } from '../../../../shared/js/ws.js';
import { checkAndTriggerGlobalOutcome } from '../home.js';

const TABS = [
  { code: 'MINDMAZE', route: '#/game/mindmaze' },
  { code: 'ACE_SPADE', route: '#/game/ace-spade' },
  { code: 'KING_DIAMOND', route: '#/game/king-diamond' },
  { code: 'JACK_HEART', route: '#/game/jack-heart' },
];

// ── JH (Jack of Hearts) card loader — animated spinning card used in place
// of the plain circular spinner, but ONLY for Jack of Hearts waiting/loading
// screens. MindMaze and King of Diamonds keep their existing loaders untouched.
const JH_CARD_FRONT_URL = '../../../../shared/assets/jh_loader_front.webp'
const JH_CARD_BACK_URL = '../../../../shared/assets/kd_loader_backside.webp'

let _jhCardLoaderStylesInjected = false;
function injectJHCardLoaderStyles() {
  if (_jhCardLoaderStylesInjected) return;
  _jhCardLoaderStylesInjected = true;
  const styleEl = document.createElement('style');
  styleEl.textContent = `
    .jh-card-loader-wrap { display: flex; justify-content: center; margin: 16px auto 12px; }
    .jh-card-loader {
      position: relative; width: 112px; height: 160px;
      animation: jh-card-float 2.8s ease-in-out infinite;
    }
    .jh-card-loader.jh-card-loader-sm { width: 72px; height: 104px; }
    .jh-card-loader-inner {
      position: relative; width: 100%; height: 100%;
      animation: jh-card-shine-glow 2.8s ease-in-out infinite;
    }
    .jh-card-face {
      position: absolute; top: 0; left: 0; right: 0; bottom: 0; 
      overflow: hidden; border-radius: 8px; 
      background-size: cover; background-position: center;
    }
    .jh-card-face-back { display: none; }
    
    .jh-card-face::after {
      content: '';
      position: absolute;
      top: -50%;
      left: -100%;
      width: 60%;
      height: 200%;

      background: linear-gradient(
        90deg,
        transparent 0%,
        transparent 35%,
        rgba(255, 255, 255, 0.15) 42%,
        rgba(255, 255, 255, 0.95) 50%,
        rgba(255, 255, 255, 0.15) 58%,
        transparent 65%
      );

      transform: rotate(15deg);
      animation: jh-card-shine 2.8s ease-in-out infinite;

      z-index: 10;
      pointer-events: none;
    }

    @keyframes jh-card-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-5px); } }
    
    @keyframes jh-card-shine-glow {
      0%, 100% { filter: drop-shadow(0 3px 6px rgba(0,0,0,0.35)) drop-shadow(0 0 8px rgba(255,220,150,0.25)); }
      50%      { filter: drop-shadow(0 5px 10px rgba(0,0,0,0.4)) drop-shadow(0 0 18px rgba(255,225,170,0.55)); }
    }
    
    @keyframes jh-card-shine {
      0% {
        left: -100%;
      }
      45% {
        left: 130%;
      }
      100% {
        left: 130%;
      }
    }
    
    @media (prefers-reduced-motion: reduce) {
      .jh-card-loader, .jh-card-loader-inner, .jh-card-face::after { animation: none !important; }
    }
  `;
  document.head.appendChild(styleEl);
}

// Renders the JH card-flip loader markup. Pass { small: true } for the
// compact version used inline within the mid-game scoreboard card.
function jhCardLoaderHTML({ small = false } = {}) {
  injectJHCardLoaderStyles();
  return `
    <div class="jh-card-loader-wrap">
      <div class="jh-card-loader${small ? ' jh-card-loader-sm' : ''}">
        <div class="jh-card-loader-inner">
          <div class="jh-card-face" style="background-image:url('${JH_CARD_FRONT_URL}');"></div>
          <div class="jh-card-face jh-card-face-back" style="background-image:url('${JH_CARD_BACK_URL}');"></div>
        </div>
      </div>
    </div>
  `;
}

/**
 * @param {object} opts
 *   gameCode: 'MINDMAZE' | 'KING_DIAMOND' | 'JACK_HEART'
 *   apiGameCode: lowercase path segment ('mindmaze' | 'king-diamond' | 'jack-heart')
 *   renderActive(container, ctx, { navigate, stopCountdown }) — ctx: { roundId, deadline, sessionId, session, roomId }
 */
export function renderGameScreen(root, navigate, opts) {
  const roomId = localStorage.getItem('bl_room_id');
  let disposed = false;
  let stopCd = null;
  let isLeaderboardPublished = false;
  // A practice round, when one is running for this game, is rendered in
  // place of the real session and drives every submit through api.demo
  // instead of api.team — nothing played here reaches the database.
  let isDemoActive = false;
  let demoAttempt = 0;
  let liveWs = null;
  let lbWs = null;
  let lastStateKey = null;

  if (roomId) {
    liveWs = new LiveChannel(`/rooms/${roomId}/sessions`, () => {
      if (!disposed) load();
    }, 'team');
    // NOTE: this channel also fires automatically from the backend when a
    // room's results are recomputed (e.g. _maybe_close_room on session
    // completion) — that is NOT the same as admin clicking "Publish to
    // Teams". Do not treat receipt of a message here as proof of publish;
    // just refetch and let load() read the real is_published flag from
    // the session API.
    lbWs = new LiveChannel(`/rooms/${roomId}/leaderboard`, () => {
      if (!disposed) load();
    }, 'team');
  }

  // Mobile fix: clears stale KD localStorage keys from old sessions
  function cleanupKDStorage(session) {
    try {
      const currentRoundIds = new Set();
      if (session?.rounds) {
        session.rounds.forEach((r) => {
          if (r.round_id) currentRoundIds.add(r.round_id);
        });
      }
      const keys = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (!k) continue;
        if (k.startsWith('bl_kd_active_round_') || k.startsWith('bl_kd_reveal_')) {
          keys.push(k);
        } else if (k.startsWith('bl_kd_shown_')) {
          const rId = k.replace('bl_kd_shown_', '');
          if (!currentRoundIds.has(rId) || !session || session.status === 'NOT_STARTED') {
            keys.push(k);
          }
        }
      }
      keys.forEach(k => localStorage.removeItem(k));
    } catch (_) { }
  }

  function cleanupMMStorage(session) {
    try {
      const activeUnsubmittedRoundIds = new Set();
      if (session?.rounds) {
        session.rounds.forEach((r) => {
          if (!r.submitted && r.round_id) {
            activeUnsubmittedRoundIds.add(r.round_id);
          }
        });
      }
      const toRemove = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith('bl_mm_')) {
          const rId = k.replace(/^bl_mm_(state|reveal)_/, '');
          if (activeUnsubmittedRoundIds.has(rId) || !session || session.status === 'NOT_STARTED') {
            toRemove.push(k);
          }
        }
      }
      toRemove.forEach(k => localStorage.removeItem(k));
    } catch (_) { }
  }

  // Same mobile-reload fix as cleanupMMStorage, for Ace of Spades' own
  // bl_as_state_/bl_as_reveal_ localStorage keys.
  function cleanupASStorage(session) {
    try {
      const activeUnsubmittedRoundIds = new Set();
      if (session?.rounds) {
        session.rounds.forEach((r) => {
          if (!r.submitted && r.round_id) {
            activeUnsubmittedRoundIds.add(r.round_id);
          }
        });
      }
      const toRemove = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith('bl_as_')) {
          const rId = k.replace(/^bl_as_(state|reveal)_/, '');
          if (activeUnsubmittedRoundIds.has(rId) || !session || session.status === 'NOT_STARTED') {
            toRemove.push(k);
          }
        }
      }
      toRemove.forEach(k => localStorage.removeItem(k));
    } catch (_) { }
  }

  root.innerHTML = `
    <div class="bracket-header"><span class="jp">${HEADERS.round.jp}</span><span class="en">${GAMES[opts.gameCode].en}</span></div>
    <div class="demo-banner" id="demo-banner" hidden>
      <span class="demo-banner-tag">${DEMO.tag.en}</span>
      <span class="demo-banner-text">
        <strong>${DEMO.banner.jp} / ${DEMO.banner.en}</strong>
        <span class="demo-banner-sub">${DEMO.bannerSub.en} — ${DEMO.bannerSub.jp}</span>
      </span>
      <span class="demo-banner-attempt" id="demo-banner-attempt"></span>
    </div>
    <button class="game-rules-fab" id="open-rules-fab-btn" title="Game Rules / ルール" type="button">
      <span class="game-rules-fab-icon">?</span>
      <span class="game-rules-fab-label">Rules</span>
    </button>
    <div class="scroll-area" id="game-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#game-body');
  const headerEl = root.querySelector('.bracket-header');

  // "Back to Home" on every end-of-game screen (published leaderboard, and
  // the "all sub-rounds done, waiting for results" screen). Delegated, since
  // body.innerHTML is rebuilt on every refresh.
  body.addEventListener('click', (e) => {
    if (e.target.closest('[data-nav-home]')) navigate('#/home');
  });
  function homeButtonHTML() {
    return `
      <div class="game-home-dock">
        <button type="button" class="cta-btn ghost game-home-btn" data-nav-home>
          <span class="game-home-arrow" aria-hidden="true">‹</span>
          <span>ホームへ戻る / HOME</span>
        </button>
      </div>`;
  }
  const demoBannerEl = root.querySelector('#demo-banner');
  const demoAttemptEl = root.querySelector('#demo-banner-attempt');

  // Jack of Hearts hides the shell's own chrome (see hideShellChrome in
  // jack-heart.js) and re-hides it on every remount, so the banner is
  // re-shown here rather than relying on it surviving that.
  function updateDemoBanner() {
    if (!demoBannerEl) return;
    demoBannerEl.hidden = !isDemoActive;
    if (isDemoActive && demoAttemptEl) {
      demoAttemptEl.textContent = demoAttempt > 1 ? `${DEMO.attempt.en} ${demoAttempt}` : '';
    }
  }

  /** api.demo and api.team expose the same method names for all three
   *  games, so the game screens only need to be handed the right one. */
  function activeGameApi() {
    return isDemoActive ? api.demo : api.team;
  }
  const rulesFabBtn = root.querySelector('#open-rules-fab-btn');
  if (rulesFabBtn) {
    rulesFabBtn.style.display = 'none'; // hidden by default until playing or waiting for subround
    rulesFabBtn.onclick = () => openRulesModal();
  }

  function updateRulesFab(show) {
    if (rulesFabBtn) {
      rulesFabBtn.style.display = show ? 'inline-flex' : 'none';
    }
  }

  let currentSession = null;

  async function load() {
    if (!roomId) {
      try {
        const activeRound = await api.team.getActiveRound().catch(() => null);
        if (activeRound && activeRound.round_id) {
          const mySel = await api.team.mySelection(activeRound.round_id).catch(() => null);
          if (mySel && mySel.room_id) {
            roomId = mySel.room_id;
            localStorage.setItem('bl_room_id', roomId);
          }
          if (mySel && mySel.suit_code) {
            localStorage.setItem('bl_team_suit', mySel.suit_code.toUpperCase());
          }
        }
      } catch (_) { }
    }

    if (!roomId) {
      updateRulesFab(false);
      body.innerHTML = `<p class="status-note">No room assigned yet — finish selection first.</p>`;
      return;
    }
    try {
      // A running practice round takes precedence over the real session:
      // the whole point is that the team plays the demo on this screen
      // while the real game sits untouched behind it.
      const [sessions, demoSessions] = await Promise.all([
        api.team.roomSessions(roomId),
        api.demo.roomSessions(roomId).catch(() => []),
      ]);

      const matchesGame = (s) =>
        s.game_code === opts.gameCode ||
        s.game_id === opts.gameCode ||
        (s.game_code && s.game_code.toUpperCase() === opts.gameCode.toUpperCase());

      const demoSession = (demoSessions || []).find(matchesGame);
      const session = demoSession || sessions.find(matchesGame);

      isDemoActive = Boolean(demoSession);
      demoAttempt = demoSession ? (demoSession.demo_attempt || 1) : 0;
      updateDemoBanner();

      isLeaderboardPublished = Boolean(session && session.is_published);
      currentSession = session;

      // View acknowledgements track who has seen the real published
      // results; a practice round has nothing to acknowledge.
      if (!isDemoActive && session && session.is_published && session.session_id) {
        api.team.viewAck(session.session_id, 'PUBLISHED_RESULTS').catch(() => { });
      }

      renderForSession(session);
    } catch (err) {
      updateRulesFab(false);
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  function renderForSession(session) {
    if (disposed) return;
    // NOTE: do NOT call stopCd() here — it would kill the countdown
    // before the stateKey dedup check, freezing the timer on mobile
    // when a WebSocket update skips the remount. stopCd() is called
    // below, right before we actually remount.

    // ── Instruction phase — takes priority over all other states ────────────
    if (session?.instruction_until) {
      const instrExp = new Date(session.instruction_until);
      if (instrExp.getTime() > (typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now())) {
        updateRulesFab(false);
        if (stopCd) { stopCd(); stopCd = null; }
        renderInstructions(instrExp);
        return;
      }
    }
    // ── End instruction check ───────────────────────────────────────────────

    if (!session || session.status === 'NOT_STARTED') {
      updateRulesFab(false);
      // Mobile fix: clear stale KD and MM localStorage when session hasn't started
      cleanupKDStorage(session);
      cleanupMMStorage(session);
      cleanupASStorage(session);
      if (stopCd) { stopCd(); stopCd = null; }

      if (opts.gameCode === 'JACK_HEART') {
        body.innerHTML = `
          <div class="result-hero" style="text-align: center; padding: var(--gap-lg) var(--gap-md);">
            ${jhCardLoaderHTML()}
            <p class="status-note" style="color: var(--bl-ink); font-weight: 700; font-size: 1.05rem; margin-top: 16px;">
              ${STATUS.waitingToStart.jp}<br>
              <span style="color:#64748b; font-size:0.8rem;">${STATUS.waitingToStart.en}</span>
            </p>
          </div>
        `;
      } else {
        body.innerHTML = `
          <div class="countdown-wrap">
            <div class="spinner"></div>
            <div class="countdown-label">${STATUS.waitingToStart.jp} / ${STATUS.waitingToStart.en}</div>
          </div>
        `;
      }
      setTimeout(load, 1000);
      return;
    }

    if (session.status === 'PAUSED') {
      updateRulesFab(false);
      if (stopCd) { stopCd(); stopCd = null; }
      body.innerHTML = `
        <div class="countdown-wrap">
          <div class="countdown-face paused">${STATUS.paused.jp}</div>
          <div class="countdown-label">${STATUS.paused.en}</div>
        </div>
      `;
      setTimeout(load, 1000);
      return;
    }

    const sessionId = session?.session_id;
    const allRoundsFinished = session.rounds && session.rounds.length && session.rounds.every((r) => r.is_closed || ((opts.gameCode === 'MINDMAZE' || opts.gameCode === 'ACE_SPADE') && r.submitted));

    // If admin has already published results, skip any pending reveals and show the final leaderboard directly!
    if (isLeaderboardPublished || session.is_published) {
      updateRulesFab(false);
      cleanupKDStorage(session);
      cleanupMMStorage(session);
      cleanupASStorage(session);
      if (stopCd) { stopCd(); stopCd = null; }
      renderCompleted(session);
      return;
    }

    if (session.status === 'COMPLETED' || allRoundsFinished) {
      updateRulesFab(false);

      // If results are NOT published yet, check if the last closed round needs to be revealed first before waiting
      const closedRounds = session.rounds ? session.rounds.filter((r) => r.is_closed) : [];
      if (opts.gameCode === 'KING_DIAMOND' && closedRounds.length > 0) {
        const lastClosed = closedRounds[closedRounds.length - 1];
        let shown = false;
        try { shown = Boolean(localStorage.getItem(`bl_kd_shown_${lastClosed.round_id}`)); } catch (_) { }
        if (!shown) {
          updateRulesFab(true);
          const container = document.createElement('div');
          body.innerHTML = '';
          body.appendChild(container);
          opts.renderActive(container, {
            roundId: lastClosed.round_id,
            roundNumber: lastClosed.round_number,
            totalRounds: closedRounds.length,
            isClosed: true,
            sessionId,
            session,
            roomId,
            isDemo: isDemoActive,
            demoAttempt,
            gameApi: activeGameApi(),
          }, { navigate, reload: load });
          return;
        }
      }

      cleanupKDStorage(session);
      cleanupMMStorage(session);
      cleanupASStorage(session);
      if (stopCd) { stopCd(); stopCd = null; }

      // If admin has not published the room results yet, wait on the waiting screen
      if (!isLeaderboardPublished && !session.is_published) {
        updateRulesFab(false);
        body.innerHTML = `
          <div class="result-hero" style="text-align: center; padding: var(--gap-lg) var(--gap-md); max-width: 480px; margin: 0 auto;">
            <div style="font-size: 0.85rem; font-weight: 800; color: var(--bl-red); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px;">
              全サブラウンド終了 / All Sub-Rounds Completed
            </div>
            <h2 style="font-size: 1.45rem; font-weight: 900; color: var(--bl-ink); margin: 0 0 8px;">
              ${GAMES[opts.gameCode]?.en || opts.gameCode} 終了
            </h2>
            <p class="status-note" style="color: var(--bl-gray); font-size: 0.92rem; margin-bottom: var(--gap-md);">
              すべてのサブラウンドが終了しました。<br>
              <span style="font-size:0.82rem;">All sub-rounds for this game have completed.</span>
            </p>
            ${opts.gameCode === 'JACK_HEART' ? jhCardLoaderHTML() : '<div class="spinner" style="margin: var(--gap-md) auto; width: 36px; height: 36px;"></div>'}
            <div style="background: #f8fafc; border: 1.5px solid #e2e8f0; border-radius: 10px; padding: 16px; margin-top: 14px;">
              <p class="status-note" style="color: var(--bl-red); font-weight: 700; font-size: 1.05rem; line-height: 1.5; margin: 0 0 6px;">
                ${isDemoActive ? DEMO.scoring.jp : '結果発表をお待ちください…'}<br>
                <span style="font-size: 0.88rem; color: #475569; font-weight: 600;">${isDemoActive ? DEMO.scoring.en : 'Waiting for Admin to publish results…'}</span>
              </p>
              <p style="font-size: 0.78rem; color: #64748b; margin: 0;">
                ${isDemoActive
                  ? `${DEMO.scoringNote.jp}<br>${DEMO.scoringNote.en}`
                  : '管理者が結果を公開すると、全チームの順位表が表示されます。<br>The full team leaderboard will be revealed once published by Admin.'}
              </p>
            </div>
            ${homeButtonHTML()}
          </div>
        `;
        setTimeout(load, 2000);
        return;
      }

      renderCompleted(session);
      return;
    }

    let ctx = null;
    const totalRounds = session.rounds ? session.rounds.length : 0;

    // 1. Is there an actively running round (has start_time and is not closed)?
    const runningRound = session.rounds?.find((r) => r.start_time && !r.is_closed);

    // 2. Are there closed rounds?
    const closedRounds = session.rounds?.filter((r) => r.is_closed) || [];
    const lastClosedRound = closedRounds.length > 0 ? closedRounds[closedRounds.length - 1] : null;

    // 3. Is there an upcoming unstarted round?
    const unstartedRound = session.rounds?.find((r) => !r.start_time && !r.is_closed);

    let targetRound = null;
    if (runningRound) {
      targetRound = runningRound;
    } else if (opts.gameCode === 'KING_DIAMOND' && lastClosedRound) {
      let shown = false;
      try { shown = Boolean(localStorage.getItem(`bl_kd_shown_${lastClosedRound.round_id}`)); } catch (_) { }
      targetRound = (!shown || !unstartedRound) ? lastClosedRound : unstartedRound;
    } else {
      targetRound = unstartedRound || (session.rounds && session.rounds[0]) || null;
    }

    if (targetRound) {
      ctx = {
        roundId: targetRound.round_id,
        deadline: targetRound.deadline,
        startTime: targetRound.start_time,
        roundNumber: targetRound.round_number,
        totalRounds,
        submitted: targetRound.submitted,
        score: targetRound.score,
        mistakes: targetRound.mistakes,
        correctTiles: targetRound.correct_tiles,
        correctPicks: targetRound.correct_picks,
        wrongPicks: targetRound.wrong_picks,
        isClosed: targetRound.is_closed,
      };
      setRoundContext(sessionId, ctx);
    } else {
      ctx = getRoundContext(sessionId);
    }

    if (headerEl) {
      if (runningRound) {
        const roundLabel = totalRounds ? `${runningRound.round_number} / ${totalRounds}` : `${runningRound.round_number}`;
        headerEl.innerHTML = `<span class="jp">${HEADERS.round.jp} ${roundLabel}</span><span class="en">${GAMES[opts.gameCode].en} (Round ${roundLabel})</span>`;
      } else if (lastClosedRound) {
        headerEl.innerHTML = `<span class="jp">サブラウンド ${lastClosedRound.round_number} 終了</span><span class="en">${GAMES[opts.gameCode].en} (Round ${lastClosedRound.round_number} Result)</span>`;
      } else {
        headerEl.innerHTML = `<span class="jp">${HEADERS.round.jp}</span><span class="en">${GAMES[opts.gameCode].en}</span>`;
      }
    }

    if (!ctx || !ctx.roundId) {
      updateRulesFab(false);
      const wrap = document.createElement('div');
      body.innerHTML = '';
      body.appendChild(wrap);
      renderRoundContextForm(wrap, sessionId, () => renderForSession(session));
      return;
    }

    // Active playing or waiting for sub-round starts here:
    updateRulesFab(true);

    if (!ctx.startTime && opts.gameCode !== 'MINDMAZE' && opts.gameCode !== 'ACE_SPADE' && opts.gameCode !== 'KING_DIAMOND') {
      if (stopCd) { stopCd(); stopCd = null; }
      if (opts.gameCode === 'JACK_HEART' && closedRounds.length === 2) {
        renderJHIntermediateScoreboard(session, closedRounds.length, unstartedRound);
      } else {
        renderWaitingForNextSubround(ctx);
      }
      return;
    }

    const nowMs = typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now();
    if (ctx.startTime && new Date(ctx.startTime).getTime() > nowMs) {
      // Already counting down to this exact start time? Leave it running.
      // A WebSocket/poll refresh landing mid-countdown used to tear the
      // 3-2-1 down and rebuild it from scratch, which showed as a flicker.
      if (stopCd && body.dataset.cdStart === ctx.startTime) return;
      if (stopCd) { stopCd(); stopCd = null; }
      body.dataset.cdStart = ctx.startTime;
      renderStartCountdown(ctx);
      return;
    }

    // Mobile fix: include ALL round IDs + deadlines so a new sub-round
    // always produces a different stateKey and triggers a remount.
    const roundSignature = session.rounds
      ? session.rounds.map(r => `${r.round_id}:${r.is_closed}:${r.start_time || ''}`).join('|')
      : '';
    const stateKey = `${opts.gameCode}_${sessionId}_${ctx.roundId}_${ctx.submitted}_${ctx.startTime}_${ctx.deadline}_${session.status}_${roundSignature}`;
    // Deduplicate: if the exact same server state was already mounted,
    // skip the remount so we don't tear down KD's auto-submit timer
    // or MindMaze's in-progress game.
    if ((opts.gameCode === 'MINDMAZE' || opts.gameCode === 'ACE_SPADE' || opts.gameCode === 'KING_DIAMOND') && lastStateKey === stateKey) {
      return;
    }
    lastStateKey = stateKey;

    // NOW safe to kill the old countdown — we are definitely remounting.
    if (stopCd) { stopCd(); stopCd = null; }

    const container = document.createElement('div');
    body.innerHTML = '';
    body.appendChild(container);

    if (ctx.deadline) {
      const cdEl = document.createElement('div');
      if (opts.gameCode === 'MINDMAZE' || opts.gameCode === 'ACE_SPADE') {
        cdEl.style.cssText = 'display: none !important;';
      } else {
        cdEl.className = 'countdown-wrap';
        cdEl.style.padding = '0 0 var(--gap-md)';
      }
      cdEl.innerHTML = `<div class="countdown-face" id="cd-face" style="font-size:1.8rem;">--:--:--</div><div class="countdown-label">${STATUS.timeRemaining.jp} / ${STATUS.timeRemaining.en}</div>`;
      container.appendChild(cdEl);
      const face = cdEl.querySelector('#cd-face');
      stopCd = startCountdown(
        ctx.deadline,
        (secs) => { face.textContent = formatCountdown(secs); },
        () => {
          face.textContent = '00:00:00';
          // Jack of Hearts has nothing left to show at 00:00 and the server
          // reports the round closed the moment the deadline passes
          // (is_closed is derived from it), so refetch straight away rather
          // than parking the team on the expired board. The short grace
          // absorbs clock-sync error: if the server hasn't crossed the
          // deadline yet, the remounted countdown expires at once and lands
          // back here. MindMaze / Ace of Spades keep the 2s — they auto-submit
          // at 00:00 and draw their score reveal in place, and this refetch is
          // what later replaces it with the waiting screen.
          setTimeout(load, opts.gameCode === 'JACK_HEART' ? 250 : 2000);
        }
      );
    }

    const activeArea = document.createElement('div');
    container.appendChild(activeArea);

    opts.renderActive(activeArea, {
      ...ctx,
      sessionId,
      session,
      roomId,
      isDemo: isDemoActive,
      demoAttempt,
      gameApi: activeGameApi(),
    }, { navigate, reload: load });
  }

  function renderStartCountdown(ctx) {
    body.innerHTML = `
      <div class="countdown-wrap" style="align-items:center; justify-content:center; padding: 40px var(--gap-md); text-align:center;">
        <div class="status-note" style="font-size:1.1rem; font-weight:700; color:var(--bl-red); text-transform:uppercase; margin-bottom:8px;">
          ${ctx.totalRounds ? `Sub-Round ${ctx.roundNumber} / ${ctx.totalRounds}` : `Sub-Round ${ctx.roundNumber}`}
        </div>
        <div class="countdown-face" id="start-count-face" style="font-size:5rem; font-weight:900; margin:12px 0; color:var(--bl-ink);">3</div>
        <div class="countdown-label">
          <span class="jp">まもなく開始します</span> / Get Ready!
        </div>
      </div>
    `;
    const face = body.querySelector('#start-count-face');

    // Warm anything the game needs to paint (e.g. Jack of Hearts' board)
    // during the countdown, so nothing is fetched at "GO!".
    if (typeof opts.prefetch === 'function') {
      try { opts.prefetch({ ...ctx, gameApi: activeGameApi(), isDemo: isDemoActive }); } catch (_) {}
    }

    stopCd = startCountdown(
      ctx.startTime,
      (secs) => {
        const intSecs = Math.ceil(secs);
        face.textContent = intSecs > 0 ? String(intSecs) : 'GO!';
      },
      () => {
        stopCd = null;
        // Mount straight from the session we already hold: the round's
        // start_time/deadline are known, so every device flips to the game at
        // the same server instant instead of after its own network round
        // trip. The refetch behind it only reconciles.
        if (currentSession) renderForSession(currentSession);
        load();
      },
    );

  }

  function renderWaitingForNextSubround(ctx) {
    body.innerHTML = `
      <div class="result-hero" style="text-align: center; padding: var(--gap-lg) var(--gap-md);">
        <p class="status-note" style="font-weight: 700; color: var(--bl-ink); font-size:1.2rem;">
          次のサブラウンドの開始をお待ちください
        </p>
        <p class="status-note" style="font-size:1rem; color:var(--bl-gray); margin-top:4px; margin-bottom:var(--gap-md);">
          Waiting for the next sub-round to start…
          ${ctx && ctx.roundNumber ? `<br><span style="font-weight:600; color:var(--bl-gray); display:inline-block; margin-top:6px;">Sub-Round ${ctx.roundNumber} (Not Started)</span>` : ''}
        </p>
        ${jhCardLoaderHTML()}
        <p class="status-note" style="color: var(--bl-red); font-weight: 600;">
          管理者による開始指示をお待ちください / Waiting for Admin to start next sub-round
        </p>
      </div>
    `;
    setTimeout(load, 1000);
  }

  // ── Suit resolution & Alice in Borderland Scoreboard Helpers ───────────
  const SUIT_SYMBOLS = { SPADE: '♠', HEART: '♥', DIAMOND: '♦', CLUB: '♣' };
  const SYMBOL_TO_CODE = { '♠': 'SPADE', '♥': 'HEART', '♦': 'DIAMOND', '♣': 'CLUB' };
  const SUIT_NAMES = { SPADE: 'Spade', HEART: 'Heart', DIAMOND: 'Diamond', CLUB: 'Club' };
  const SUIT_CYCLE = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];

  function resolveTeamSuit(r, idx, isMe) {
    let code = (r.team_suit_code || r.suit_code || r.suit || '').toUpperCase();
    if ((!code || !SUIT_SYMBOLS[code]) && r.team_suit_symbol) {
      code = SYMBOL_TO_CODE[r.team_suit_symbol] || '';
    }
    if ((!code || !SUIT_SYMBOLS[code]) && isMe) {
      code = (localStorage.getItem('bl_team_suit') || localStorage.getItem('bl_suit') || '').toUpperCase();
    }
    if (!code || !SUIT_SYMBOLS[code]) {
      code = SUIT_CYCLE[idx % 4];
    }
    return {
      code,
      symbol: SUIT_SYMBOLS[code] || '♠',
      name: SUIT_NAMES[code] || 'Spade',
    };
  }

  async function enrichRowsWithRoomSuits(rows, rId) {
    if (!rows || !rows.length) return rows;
    const missingAnySuit = rows.some(r => !r.team_suit_code && !r.suit_code && !r.suit);
    if (!missingAnySuit || !rId) return rows;
    try {
      const roomLb = await api.team.roomLeaderboard(rId);
      if (roomLb && roomLb.length) {
        const suitMap = {};
        roomLb.forEach(entry => {
          if (entry.team_code) {
            suitMap[entry.team_code] = {
              code: entry.team_suit_code,
              symbol: entry.team_suit_symbol
            };
          }
        });
        rows.forEach(r => {
          if ((!r.team_suit_code && !r.suit_code && !r.suit) && r.team_code && suitMap[r.team_code]) {
            r.team_suit_code = suitMap[r.team_code].code;
            r.team_suit_symbol = suitMap[r.team_code].symbol;
          }
        });
      }
    } catch (_) { }
    return rows;
  }

  function buildAIBScoreboardHTML({
    tag = 'GAME CLEAR',
    title = 'GAME',
    titleAccent = 'LEADERBOARD',
    subtitle = '全サブラウンド終了 / FINAL RESULTS',
    rows = [],
    scoreLabel = 'POINTS',
    formatScoreFn = null,
    subroundsHTML = '',
    footerHTML = '',
  }) {
    return `
      <div class="result-hero bl-scoreboard-wrapper">
        <div class="bl-aib-scoreboard">
          <div class="bl-aib-header-banner">
            <div class="bl-aib-tag-pill">
              <span class="bl-aib-pulse-dot"></span>
              <span>${tag}</span>
            </div>
            <h2 class="bl-aib-title-main">
              ${title} <span class="bl-aib-accent">${titleAccent}</span>
            </h2>
            <div class="bl-aib-subtitle">${subtitle}</div>
          </div>

          <div class="bl-aib-col-headers">
            <div class="bl-aib-th-pos">RANK</div>
            <div class="bl-aib-th-team">TEAM & SUIT</div>
            <div class="bl-aib-th-scores">${scoreLabel}</div>
          </div>

          <div class="bl-aib-list">
            ${rows.map((r, idx) => {
              const isMe = Boolean(r.is_current_team || r.is_me);
              const rank = r.rank ?? r.live_rank ?? r.game_rank ?? (idx + 1);
              const rankNum = `${rank}`;
              const suit = resolveTeamSuit(r, idx, isMe);
              const displayName = r.team_name || r.team_code;
              const youBadge = isMe ? '<span class="bl-aib-you-tag">YOU</span>' : '';
              const scoreVal = formatScoreFn ? formatScoreFn(r) : (r.total_score !== undefined ? `${Number(r.total_score).toFixed(1)} PTS` : (r.score !== undefined ? `${r.score} PTS` : '—'));
              const rankClass = rank === 1 ? 'p1' : rank === 2 ? 'p2' : rank === 3 ? 'p3' : '';

              return `
                <div class="bl-aib-row suit-${suit.code.toLowerCase()} ${rankClass} ${isMe ? 'me' : ''}">
                  <div class="bl-aib-rank-box">
                    <span class="bl-aib-rank-num">${rankNum}</span>
                  </div>

                  <div class="bl-aib-team-info">
                    <div class="bl-aib-team-name" title="${displayName}">${displayName}</div>
                    <div class="bl-aib-team-meta">
                      <div class="bl-aib-suit-badge suit-${suit.code.toLowerCase()}">
                        <span class="bl-aib-suit-icon">${suit.symbol}</span>
                        <span>${suit.name}</span>
                      </div>
                      ${youBadge}
                    </div>
                  </div>

                  <div class="bl-aib-scores-box">
                    <div class="bl-aib-score-cell">${scoreVal}</div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>

          ${footerHTML}
        </div>
      </div>
    `;
  }

  function buildSubroundsHTML() {
    return '';
  }

  async function renderJHIntermediateScoreboard(session, closedCount, nextRound) {
    if (!isDemoActive && session?.session_id) {
      const closedList = session.rounds ? session.rounds.filter(r => r.is_closed) : [];
      const lastClosed = closedList.length > 0 ? closedList[closedList.length - 1] : null;
      api.team.viewAck(session.session_id, 'JH_MID_GAME', lastClosed?.round_id).catch(() => { });
    }

    let rows = [];
    if (isDemoActive) {
      try { rows = await api.demo.jackHeartLeaderboard(roomId); } catch (_) { rows = []; }
    } else {
      try {
        rows = await api.team.jackHeartLeaderboard(roomId);
      } catch (_) {
        try { rows = await api.team.roomLeaderboard(roomId); } catch (_) { rows = []; }
      }
    }
    rows = await enrichRowsWithRoomSuits(rows, roomId);

    const waitingFooterHTML = `
      <div class="bl-aib-status-card">
        ${jhCardLoaderHTML({ small: true })}
        <div class="bl-aib-status-jp">サブラウンド${nextRound ? nextRound.round_number : closedCount + 1}の開始をお待ちください…</div>
        <div class="bl-aib-status-en">Waiting for Admin to start next sub-round…</div>
      </div>
    `;

    body.innerHTML = buildAIBScoreboardHTML({
      tag: isDemoActive ? 'PRACTICE ARENA' : 'MID-GAME STANDINGS',
      title: 'JACK OF HEARTS',
      titleAccent: 'SURVIVAL LADDER',
      subtitle: `サブラウンド${closedCount} 終了 / SUB-ROUND ${closedCount} COMPLETE`,
      rows,
      scoreLabel: 'POINTS',
      formatScoreFn: (r) => (r.total_score !== undefined ? `${Number(r.total_score).toFixed(1)} PTS` : (r.jack_heart_score !== undefined ? `${Number(r.jack_heart_score).toFixed(1)} PTS` : '—')),
      footerHTML: waitingFooterHTML,
    });

    setTimeout(load, 1500);
  }

  async function renderCompleted(sessionParam) {
    updateRulesFab(false);
    const appEl = document.getElementById('app');
    if (appEl) appEl.classList.add('has-scoreboard');
    try {
      const activeSession = sessionParam || currentSession;
      if (!isDemoActive && activeSession?.session_id) {
        api.team.viewAck(activeSession.session_id, 'PUBLISHED_RESULTS').catch(() => { });
      }

      if (opts.gameCode === 'MINDMAZE' && roomId) {
        let rows = [];
        if (isDemoActive) {
          try { rows = await api.demo.mindmazeLeaderboard(roomId); } catch (_) { rows = []; }
        } else {
          try {
            rows = await api.team.mindmazeLeaderboard(roomId);
          } catch (_) {
            rows = await api.team.gameLeaderboard(opts.gameCode);
          }
        }
        rows = await enrichRowsWithRoomSuits(rows, roomId);

        body.innerHTML = buildAIBScoreboardHTML({
          tag: isDemoActive ? 'PRACTICE ARENA' : 'STAGE CLEAR',
          footerHTML: homeButtonHTML(),
          title: 'MINDMAZE',
          titleAccent: 'LEADERBOARD',
          subtitle: '全ラウンド終了 / FINAL RESULTS',
          rows,
          scoreLabel: 'POINTS',
          formatScoreFn: (r) => {
            const scoreVal = r.total_score !== undefined ? r.total_score : r.score;
            return `${scoreVal !== undefined ? Number(scoreVal).toFixed(1) : '—'} PTS`;
          },
        });
        return;
      }

      if (opts.gameCode === 'ACE_SPADE' && roomId) {
        let rows = [];
        if (isDemoActive) {
          try { rows = await api.demo.aceSpadeLeaderboard(roomId); } catch (_) { rows = []; }
        } else {
          try {
            rows = await api.team.aceSpadeLeaderboard(roomId);
          } catch (_) {
            rows = await api.team.gameLeaderboard(opts.gameCode);
          }
        }
        rows = await enrichRowsWithRoomSuits(rows, roomId);

        body.innerHTML = buildAIBScoreboardHTML({
          tag: isDemoActive ? 'PRACTICE ARENA' : 'STAGE CLEAR',
          footerHTML: homeButtonHTML(),
          title: 'ACE OF SPADES',
          titleAccent: 'LEADERBOARD',
          subtitle: '全ラウンド終了 / FINAL RESULTS',
          rows,
          scoreLabel: 'POINTS',
          formatScoreFn: (r) => {
            const scoreVal = r.total_score !== undefined ? r.total_score : r.score;
            return `${scoreVal !== undefined ? Number(scoreVal).toFixed(1) : '—'} PTS`;
          },
        });
        return;
      }

      if (opts.gameCode === 'JACK_HEART' && roomId) {
        let rows = [];
        if (isDemoActive) {
          try { rows = await api.demo.jackHeartLeaderboard(roomId); } catch (_) { rows = []; }
        } else {
          try {
            rows = await api.team.jackHeartLeaderboard(roomId);
          } catch (_) {
            try { rows = await api.team.roomLeaderboard(roomId); } catch (_) { rows = []; }
          }
        }
        rows = await enrichRowsWithRoomSuits(rows, roomId);

        body.innerHTML = buildAIBScoreboardHTML({
          tag: isDemoActive ? 'PRACTICE ARENA' : 'GAME CLEAR',
          footerHTML: homeButtonHTML(),
          title: 'JACK OF HEARTS',
          titleAccent: 'LEADERBOARD',
          subtitle: '全ラウンド終了 / FINAL RESULTS',
          rows,
          scoreLabel: 'POINTS',
          formatScoreFn: (r) => (r.total_score !== undefined ? `${Number(r.total_score).toFixed(1)} PTS` : (r.jack_heart_score !== undefined ? `${Number(r.jack_heart_score).toFixed(1)} PTS` : '—')),
        });
        return;
      }

      if (opts.gameCode === 'KING_DIAMOND' && roomId) {
        let rows = [];
        if (isDemoActive) {
          try {
            rows = await (api.demo.kingDiamondLeaderboard ? api.demo.kingDiamondLeaderboard(roomId) : api.demo.gameLeaderboard(roomId, 'KING_DIAMOND'));
          } catch (_) {
            rows = [];
          }
        } else {
          try {
            rows = await api.team.kingDiamondLeaderboard(roomId);
          } catch (_) {
            try { rows = await api.team.roomLeaderboard(roomId); } catch (_) { rows = []; }
          }
        }
        rows = await enrichRowsWithRoomSuits(rows, roomId);

        // If admin has not published room results yet, display the Alice in Borderland waiting screen
        if (!rows || rows.length === 0) {
          body.innerHTML = `
            <div class="result-hero bl-scoreboard-wrapper">
              <div class="bl-aib-scoreboard" style="text-align:center; padding: 28px 16px;">
                <div class="bl-aib-tag-pill">
                  <span class="bl-aib-pulse-dot"></span>
                  <span>STAGE COMPLETE</span>
                </div>
                <h2 class="bl-aib-title-main" style="margin: 8px 0;">全ラウンド終了 / ALL ROUNDS FINISHED</h2>
                <p class="status-note" style="color: #475569; font-size: 0.88rem; margin-bottom: 20px;">すべてのサブラウンドが終了しました / All sub-rounds have completed.</p>
                <div class="spinner" style="margin: 16px auto;"></div>
                <div class="bl-aib-status-card">
                  <div class="bl-aib-status-jp">結果発表をお待ちください…</div>
                  <div class="bl-aib-status-en">Waiting for Admin to reveal results…</div>
                </div>
                ${homeButtonHTML()}
              </div>
            </div>
          `;
          setTimeout(load, 3000);
          return;
        }

        const totalRounds = activeSession?.rounds ? activeSession.rounds.length : (rows[0]?.subrounds ? rows[0].subrounds.length : 5);
        body.innerHTML = buildAIBScoreboardHTML({
          tag: isDemoActive ? 'PRACTICE ARENA' : 'GAME CLEAR',
          footerHTML: homeButtonHTML(),
          title: 'KING OF DIAMONDS',
          titleAccent: 'LEADERBOARD',
          subtitle: '全ラウンド終了 / FINAL RESULTS',
          rows,
          scoreLabel: 'REMAINING',
          formatScoreFn: (r) => {
            const kdScore = r.king_diamond_score ?? r.total_score ?? r.score ?? 0;
            const roundsCount = r.subrounds?.length || totalRounds;
            const maxPts = roundsCount * 20;
            return `${Number(kdScore).toFixed(1)} / ${maxPts} PTS`;
          },
        });
        return;
      }
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }

    // ── Final outcome (VISA Extended / Sky Laser) after the admin publishes ──
    // One code path decides this for the whole app (keyed on the broadcast
    // id, so a re-send replays it and each send is acknowledged once).
    if (!isDemoActive && opts.gameCode === 'JACK_HEART' && roomId) {
      checkAndTriggerGlobalOutcome();
    }
  }

  // ── Returns game-specific animated visual diagram HTML ──────────────────
  // Returns { html, start(container) → stopFn } — caller mounts the html
  // into .instr-visual, then calls start() to kick off the animation loop.
  function getAnimatedVisual(gameCode) {

    // ── MindMaze: Flash → Pointing Hand Tapping → Score cycle ────────────
    if (gameCode === 'MINDMAZE') {
      const GRID = 36;
      const LIT = [2, 7, 10, 13, 20, 22, 28];
      const TAP_SEQUENCE = [7, 13, 20, 22, 28, 15]; // 15 is an intentional mistake for demo

      let cells = '';
      for (let i = 0; i < GRID; i++) {
        cells += `<div class="mm-anim-tile" data-i="${i}"></div>`;
      }

      const html = `
        <div class="instr-visual-label">How it works</div>
        <div class="mm-anim-wrap">
          <div class="mm-anim-grid-wrap">
            <div class="mm-anim-grid">${cells}</div>
            <div class="mm-pointer-hand" id="mm-pointer-hand"></div>
          </div>
          <div class="mm-anim-phase" id="mm-anim-phase">① Memorise (Flash)</div>
          <div class="mm-anim-score" id="mm-anim-score"></div>
        </div>
      `;

      function start(container) {
        let timers = [];
        let stopped = false;
        const sched = (fn, ms) => { const t = setTimeout(() => { if (!stopped) fn(); }, ms); timers.push(t); };

        function cycle() {
          if (stopped) return;
          const tiles = container.querySelectorAll('.mm-anim-tile');
          const phase = container.querySelector('#mm-anim-phase');
          const score = container.querySelector('#mm-anim-score');
          const hand = container.querySelector('#mm-pointer-hand');
          const gridWrap = container.querySelector('.mm-anim-grid-wrap');
          if (!tiles.length || !phase) return;

          // Reset all
          tiles.forEach(t => { t.className = 'mm-anim-tile'; });
          if (score) { score.className = 'mm-anim-score'; score.innerHTML = ''; }
          if (hand) {
            hand.style.opacity = '0';
            hand.classList.remove('tap');
            hand.style.top = '10px';
            hand.style.left = '10px';
          }
          phase.textContent = '① Memorise (Flash)';

          // Phase 1: Flash tiles with ripple stagger (0–1.8s)
          LIT.forEach((idx, si) => {
            sched(() => {
              if (tiles[idx]) tiles[idx].classList.add('anim-flash');
            }, si * 75);
          });

          // Phase 2: All go dark, pointer hand appears and taps tiles (2.0s–4.6s)
          sched(() => {
            phase.textContent = '② Recall (Tap Tiles)';
            tiles.forEach(t => {
              t.classList.remove('anim-flash');
              t.classList.add('anim-dark');
            });

            if (hand && gridWrap) {
              const firstTile = tiles[TAP_SEQUENCE[0]];
              if (firstTile) {
                hand.style.top = `${firstTile.offsetTop + firstTile.offsetHeight / 2}px`;
                hand.style.left = `${firstTile.offsetLeft + firstTile.offsetWidth / 2}px`;
              }
              hand.style.opacity = '1';
            }

            // Tap sequence
            TAP_SEQUENCE.forEach((tileIdx, step) => {
              const delay = 400 + step * 380;
              sched(() => {
                const targetTile = tiles[tileIdx];
                if (!targetTile || !hand || !gridWrap) return;

                // Move hand to tile center
                hand.style.top = `${targetTile.offsetTop + targetTile.offsetHeight / 2}px`;
                hand.style.left = `${targetTile.offsetLeft + targetTile.offsetWidth / 2}px`;

                // Tap animation down
                sched(() => {
                  if (hand) hand.classList.add('tap');
                  targetTile.classList.remove('anim-dark');
                  targetTile.classList.add('anim-selected');

                  // Tap release
                  sched(() => {
                    if (hand) hand.classList.remove('tap');
                  }, 120);
                }, 180);
              }, delay);
            });
          }, 2000);

          // Phase 3: Reveal results and score (4.8s)
          sched(() => {
            phase.textContent = '③ Score (Result)';
            if (hand) hand.style.opacity = '0';

            tiles.forEach(t => t.classList.remove('anim-dark'));

            // Show correct / wrong
            TAP_SEQUENCE.forEach((tileIdx) => {
              const tile = tiles[tileIdx];
              if (!tile) return;
              tile.classList.remove('anim-selected');
              if (LIT.includes(tileIdx)) {
                tile.classList.add('anim-correct');
              } else {
                tile.classList.add('anim-wrong');
              }
            });

            // Score counter
            sched(() => {
              if (score) {
                score.innerHTML = `<span style="color:var(--bl-ink);">Score: <strong style="color:#1a7a3c; font-size:1.05rem;">+4.5 pts</strong></span> <span style="font-size:0.72rem; color:var(--bl-gray); font-weight:600; margin-left:4px;">(5 Correct · 1 Mistake)</span>`;
                score.classList.add('visible');
              }
            }, 300);
          }, 4800);

          // Restart cycle
          sched(cycle, 7500);
        }

        cycle();
        return () => { stopped = true; timers.forEach(clearTimeout); };
      }

      return { html, start };
    }

    // ── Ace of Spades: Memorize order → shuffle+decoys → tap back ────────
    if (gameCode === 'ACE_SPADE') {
      const MEMO_CARDS = [
        { suit: '♠', rank: 'A', red: false },
        { suit: '♥', rank: '7', red: true },
        { suit: '♣', rank: '4', red: false },
        { suit: '♦', rank: '9', red: true },
      ];
      const DECOYS = [
        { suit: '♣', rank: '2', red: false },
        { suit: '♦', rank: '6', red: true },
        { suit: '♠', rank: '8', red: false },
        { suit: '♥', rank: '3', red: true },
      ];
      // Recall order: memo cards shuffled in with the 4 decoys.
      const RECALL_CARDS = [MEMO_CARDS[1], DECOYS[0], MEMO_CARDS[0], DECOYS[1], MEMO_CARDS[2], DECOYS[2], MEMO_CARDS[3], DECOYS[3]];
      // Correct tap sequence (indices into RECALL_CARDS) to reproduce memo order 0,1,2,3
      const TAP_SEQUENCE = [2, 0, 4, 6];

      const cardFaceHTML = (c) => `
        <div class="as-card-corner as-card-corner-tl ${c.red ? 'as-red' : 'as-black'}">
          <span class="as-corner-rank">${c.rank}</span>
          <span class="as-corner-suit">${c.suit}</span>
        </div>
        <div class="as-card-center-suit ${c.red ? 'as-red' : 'as-black'}">${c.suit}</div>
        <div class="as-card-corner as-card-corner-br ${c.red ? 'as-red' : 'as-black'}">
          <span class="as-corner-rank">${c.rank}</span>
          <span class="as-corner-suit">${c.suit}</span>
        </div>
      `;

      const memoCellsHTML = MEMO_CARDS.map((c, i) => `
        <div class="as-anim-memo-cell">
          <div class="as-anim-card" data-i="${i}">${cardFaceHTML(c)}</div>
          <div class="as-anim-order">${i + 1}</div>
        </div>
      `).join('');

      const recallCellsHTML = RECALL_CARDS.map((c, i) => `
        <div class="as-anim-card as-anim-recall" data-ri="${i}">
          ${cardFaceHTML(c)}
          <span class="as-anim-badge" data-badge="${i}"></span>
        </div>
      `).join('');

      const html = `
        <div class="instr-visual-label">How it works</div>
        <div class="as-anim-wrap">
          <div class="as-anim-phase" id="as-anim-phase">① Memorise the order (30s)</div>
          <div class="as-anim-grid as-anim-grid-memo" id="as-anim-memo-grid">${memoCellsHTML}</div>
          <div class="as-anim-grid as-anim-grid-recall" id="as-anim-recall-grid" style="display:none;">
            ${recallCellsHTML}
            <div class="as-pointer-hand" id="as-pointer-hand"></div>
          </div>
          <div class="as-anim-score" id="as-anim-score"></div>
        </div>
      `;

      function start(container) {
        let timers = [];
        let stopped = false;
        const sched = (fn, ms) => { const t = setTimeout(() => { if (!stopped) fn(); }, ms); timers.push(t); };

        function cycle() {
          if (stopped) return;
          const phase = container.querySelector('#as-anim-phase');
          const memoGrid = container.querySelector('#as-anim-memo-grid');
          const recallGrid = container.querySelector('#as-anim-recall-grid');
          const score = container.querySelector('#as-anim-score');
          const hand = container.querySelector('#as-pointer-hand');
          if (!phase || !memoGrid || !recallGrid) return;

          // Reset
          memoGrid.style.display = 'grid';
          recallGrid.style.display = 'none';
          if (score) { score.className = 'as-anim-score'; score.innerHTML = ''; }
          recallGrid.querySelectorAll('.as-anim-card').forEach(c => { c.classList.remove('as-anim-correct', 'as-anim-wrong'); });
          recallGrid.querySelectorAll('.as-anim-badge').forEach(b => { b.textContent = ''; b.classList.remove('as-anim-badge-on'); });
          if (hand) { hand.style.opacity = '0'; hand.classList.remove('tap'); }
          phase.textContent = '① Memorise the order (30s)';

          memoGrid.querySelectorAll('.as-anim-card').forEach((c, i) => {
            sched(() => c.classList.add('as-anim-flash'), i * 120);
          });

          // Phase 2: hide, reshuffle with decoys
          sched(() => {
            phase.textContent = '② +2 decoys mixed in, reshuffled (40s)';
            memoGrid.style.display = 'none';
            recallGrid.style.display = 'grid';
          }, 1800);

          // Phase 3: pointer taps back the memorised order
          sched(() => {
            phase.textContent = '③ Tap back in the memorised order';
            const cells = recallGrid.querySelectorAll('.as-anim-card');
            TAP_SEQUENCE.forEach((cellIdx, step) => {
              const delay = step * 500;
              sched(() => {
                const target = cells[cellIdx];
                if (!target || !hand) return;
                hand.style.top = `${target.offsetTop + target.offsetHeight / 2}px`;
                hand.style.left = `${target.offsetLeft + target.offsetWidth / 2}px`;
                hand.style.opacity = '1';
                sched(() => {
                  hand.classList.add('tap');
                  const badge = target.querySelector('.as-anim-badge');
                  if (badge) { badge.textContent = String(step + 1); badge.classList.add('as-anim-badge-on'); }
                  target.classList.add('as-anim-correct');
                  sched(() => hand.classList.remove('tap'), 120);
                }, 180);
              }, delay);
            });
          }, 2600);

          // Phase 4: score reveal
          sched(() => {
            if (hand) hand.style.opacity = '0';
            phase.textContent = '④ Score (Result)';
            if (score) {
              score.innerHTML = `<span style="color:var(--bl-ink);">Score: <strong style="color:#1a7a3c; font-size:1.05rem;">+4.0 pts</strong></span> <span style="font-size:0.72rem; color:var(--bl-gray); font-weight:600; margin-left:4px;">(4 Correct · 0 Wrong)</span>`;
              score.classList.add('visible');
            }
          }, 5000);

          sched(cycle, 7800);
        }

        cycle();
        return () => { stopped = true; timers.forEach(clearTimeout); };
      }

      return { html, start };
    }

    // ── King of Diamonds: Blueprint result reveal simulation ─────────────
    if (gameCode === 'KING_DIAMOND') {
      const teams = [
        { code: 'TEAM A', initials: 'TA', val: 40, penalty: '-1.2', isWinner: false },
        { code: 'TEAM B', initials: 'TB', val: 52, penalty: '0.0',  isWinner: true },
        { code: 'TEAM C', initials: 'TC', val: 80, penalty: '-3.6', isWinner: false },
        { code: 'TEAM D', initials: 'TD', val: 70, penalty: '-2.4', isWinner: false },
      ];

      const cardsHTML = teams.map((t, i) => `
        <div class="kd-instr-team-card" data-ti="${i}">
          <div class="kd-instr-icon">${t.initials}</div>
          <div class="kd-instr-team-name">${t.code}</div>
          <div class="kd-instr-team-num">—</div>
          <span class="kd-instr-win-flag">WIN</span>
          <div class="kd-instr-deduct">${t.penalty}</div>
        </div>
      `).join('');

      const html = `
        <div class="instr-visual-label">Game mechanics in action</div>
        <div class="kd-instr-card">
          <div class="kd-instr-eyebrow">Example Sub-Round Simulation</div>
          <div class="kd-instr-title">Target Computation: Avg × 0.8</div>
          <div class="kd-instr-beam-wrap"><div class="kd-instr-beam" id="kd-instr-beam"></div></div>
          <div class="kd-instr-teams">${cardsHTML}</div>
          <div class="kd-instr-calc" id="kd-instr-calc">
            <div class="kd-instr-calc-label">Average × 0.8 Computation</div>
            <div class="kd-instr-formula" id="kd-instr-formula">&nbsp;</div>
            <div class="kd-instr-target-row">
              <span class="kd-instr-target-label">Target (Closest Wins)</span>
              <span class="kd-instr-target" id="kd-instr-target">—</span>
            </div>
          </div>
          <div class="kd-instr-outcome" id="kd-instr-outcome">
            <strong>Team B (52)</strong> is closest to target <strong>48.4</strong> → <strong>Wins Round ★</strong><br>
            <span style="font-size:0.62rem; opacity:0.85;">Winner loses 0 pts · Others lose penalty points based on distance</span>
          </div>
        </div>
      `;

      function start(container) {
        let timers = [];
        let stopped = false;
        const sched = (fn, ms) => { const t = setTimeout(() => { if (!stopped) fn(); }, ms); timers.push(t); };

        function cycle() {
          if (stopped) return;
          const cardEls  = container.querySelectorAll('.kd-instr-team-card');
          const beam     = container.querySelector('#kd-instr-beam');
          const calc     = container.querySelector('#kd-instr-calc');
          const formula  = container.querySelector('#kd-instr-formula');
          const target   = container.querySelector('#kd-instr-target');
          const outcome  = container.querySelector('#kd-instr-outcome');

          // Reset all
          cardEls.forEach(c => {
            c.className = 'kd-instr-team-card';
            const numEl = c.querySelector('.kd-instr-team-num');
            if (numEl) numEl.textContent = '—';
            const dedEl = c.querySelector('.kd-instr-deduct');
            if (dedEl) dedEl.classList.remove('in');
          });
          if (beam) { beam.className = 'kd-instr-beam'; }
          if (calc) { calc.classList.remove('in'); }
          if (formula) { formula.textContent = ''; }
          if (target) { target.className = 'kd-instr-target'; target.textContent = '—'; }
          if (outcome) { outcome.classList.remove('in'); }

          // Phase 1: Team cards appear staggered (0–0.8s)
          cardEls.forEach((el, i) => {
            sched(() => { el.classList.add('in'); }, i * 140);
          });

          // Phase 2: Beam wobbles & numbers count up (1.0s–2.4s)
          sched(() => {
            if (beam) beam.classList.add('weighing');
            cardEls.forEach((el, i) => {
              sched(() => {
                const numEl = el.querySelector('.kd-instr-team-num');
                if (numEl) {
                  numEl.textContent = teams[i].val;
                  numEl.style.animation = 'kd-instr-pop 0.3s ease';
                }
              }, i * 180);
            });
          }, 1000);

          // Phase 3: Formula and target calculation (2.6s–4.2s)
          sched(() => {
            if (calc) calc.classList.add('in');
            if (formula) formula.textContent = '(40 + 52 + 80 + 70) ÷ 4 = 60.5  →  × 0.8';

            sched(() => {
              if (target) {
                target.textContent = '48.4';
                target.classList.add('in');
              }
            }, 600);
          }, 2600);

          // Phase 4: Beam settles, winner card lights up, deductions & outcome show (4.4s–6.0s)
          sched(() => {
            if (beam) {
              beam.classList.remove('weighing');
              beam.classList.add('settled');
            }

            cardEls.forEach((el, i) => {
              if (teams[i].isWinner) {
                el.classList.add('winner');
              } else {
                el.classList.add('dim');
              }
              const ded = el.querySelector('.kd-instr-deduct');
              if (ded) ded.classList.add('in');
            });

            sched(() => {
              if (outcome) outcome.classList.add('in');
            }, 400);
          }, 4400);

          // Restart cycle
          sched(cycle, 7500);
        }

        cycle();
        return () => { stopped = true; timers.forEach(clearTimeout); };
      }

      return { html, start };
    }

    // ── Jack of Hearts: Deal → Shimmer → Arrows → Flip ──────────────────
    if (gameCode === 'JACK_HEART') {
      const cards = [
        { sym: '♠ 7',  label: 'Team A (♠)', you: false, isRed: false, rot: -8 },
        { sym: '♥ A',  label: 'Team B (♥)', you: false, isRed: true,  rot: -3 },
        { sym: '♣ ?',  label: 'You (♣)',    you: true,  isRed: false, rot: 5  },
        { sym: '♦ 10', label: 'Team D (♦)', you: false, isRed: true,  rot: 8  },
      ];

      const cardHTML = cards.map((c, i) => `
        <div class="jh-anim-card${c.you ? ' jh-anim-you' : ''}${c.isRed ? ' card-red' : ''}" data-i="${i}" style="--deal-rot:${c.rot}">
          ${c.you ? `<span class="jh-anim-q">♣ ?</span>` : c.sym}
          <span class="jh-anim-owner">${c.label}</span>
        </div>
      `).join('');

      const arrowCount = 5;
      let arrows = '';
      for (let i = 0; i < arrowCount; i++) {
        arrows += `<div class="jh-anim-arrow" data-ai="${i}"></div>`;
      }

      const html = `
        <div class="instr-visual-label">What you see vs what's hidden</div>
        <div class="jh-anim-board">${cardHTML}</div>
        <div class="jh-anim-arrows">${arrows}</div>
        <div class="jh-anim-legend">
          <span><span class="jh-anim-legend-dot"></span>Visible to you</span>
          <span><span class="jh-anim-legend-dot jh-anim-legend-red"></span>Hidden from you</span>
        </div>
        <div class="jh-anim-note" id="jh-anim-note">
          Your card is strictly from your team's suit (♣) — communicate to deduce the number! (+5.0 / 0 pts)
        </div>
      `;

      function start(container) {
        let timers = [];
        let stopped = false;
        const sched = (fn, ms) => { const t = setTimeout(() => { if (!stopped) fn(); }, ms); timers.push(t); };

        function cycle() {
          if (stopped) return;
          const cardEls  = container.querySelectorAll('.jh-anim-card');
          const arrowEls = container.querySelectorAll('.jh-anim-arrow');
          const note     = container.querySelector('#jh-anim-note');
          const youCard  = container.querySelector('.jh-anim-you');

          // Reset
          cardEls.forEach(c => { c.className = c.className.replace(/ ?anim-\w+/g, ''); c.style.opacity = '0'; });
          cardEls.forEach(c => {
            // Restore base classes
            const i = parseInt(c.dataset.i);
            c.className = `jh-anim-card${cards[i].you ? ' jh-anim-you' : ''}${cards[i].isRed ? ' card-red' : ''}`;
            c.style.opacity = '0';
          });
          arrowEls.forEach(a => { a.classList.remove('anim-flow'); });
          if (note) { note.classList.remove('anim-in'); }
          // Restore the "♣ ?" in the you-card
          if (youCard) {
            const qSpan = youCard.querySelector('.jh-anim-q');
            if (qSpan) {
              qSpan.textContent = '♣ ?';
              qSpan.style.cssText = '';
            }
          }

          // Phase 1: Deal cards from bottom with stagger (0–1.5s)
          cardEls.forEach((el, i) => {
            sched(() => {
              el.style.opacity = '';
              el.classList.add('anim-deal');
              el.style.setProperty('animation-delay', `${i * 150}ms`);
            }, i * 150);
          });

          // Phase 2: "♣ ?" shimmer pulse (1.8s)
          sched(() => {
            if (youCard) {
              youCard.classList.add('anim-shimmer', 'anim-pulse');
            }
          }, 1800);

          // Phase 3: Arrows flow (3s)
          arrowEls.forEach((a, i) => {
            sched(() => { a.classList.add('anim-flow'); }, 3000 + i * 120);
          });

          // Note slides in
          sched(() => { if (note) note.classList.add('anim-in'); }, 3500);

          // Phase 4: Card flip reveal (4.5s)
          sched(() => {
            if (youCard) {
              youCard.classList.remove('anim-shimmer', 'anim-pulse');
              youCard.classList.add('anim-flip');
              // Mid-flip: swap content
              sched(() => {
                const qSpan = youCard.querySelector('.jh-anim-q');
                if (qSpan) {
                  qSpan.textContent = '♣ 3';
                  qSpan.style.cssText = 'font-size:1.1rem; color: var(--bl-ink); -webkit-text-fill-color: var(--bl-ink); font-weight:700;';
                }
              }, 300);
            }
          }, 4500);

          // Restart cycle
          sched(cycle, 6500);
        }

        cycle();
        return () => { stopped = true; timers.forEach(clearTimeout); };
      }

      return { html, start };
    }

    // Fallback
    return { html: '', start: () => () => {} };
  }

  // ── Renders full bilingual instruction screen with visual + steps ────────
  let stopVisualAnim = null;

  function renderInstructions(expiresAt) {
    // Clean up any prior visual animation
    if (stopVisualAnim) { stopVisualAnim(); stopVisualAnim = null; }

    const instr = INSTRUCTIONS[opts.gameCode];
    const visual = getAnimatedVisual(opts.gameCode);

    const stepsHTML = instr.steps.map((s, i) => `
      <li style="--stagger-i:${i}">
        <div class="instr-step-num">${i + 1}</div>
        <div class="instr-step-text">
          <span class="en">${s.en}</span>
          <span class="jp">${s.jp}</span>
        </div>
      </li>
    `).join('');

    body.innerHTML = `
      <div class="bracket-header">
        <span class="jp">${instr.jp}</span>
        <span class="en">${instr.en}</span>
      </div>
      <div class="instr-shell">
        <div class="instr-visual">
          ${visual.html}
        </div>
        <ol class="instr-steps">${stepsHTML}</ol>
        <div class="instr-countdown">
          <div class="instr-cd-face" id="instr-cd-face">--:--</div>
          <div class="instr-cd-label">説明表示時間 / Instructions visible for</div>
          <div class="instr-progress-wrap">
            <div class="instr-progress-bar" id="instr-progress-bar" style="width:100%"></div>
          </div>
        </div>
      </div>
    `;

    // Start visual animation loop
    const visualContainer = body.querySelector('.instr-visual');
    if (visualContainer) {
      stopVisualAnim = visual.start(visualContainer);
    }

    // Countdown timer
    const face = body.querySelector('#instr-cd-face');
    const progressBar = body.querySelector('#instr-progress-bar');
    const totalMs = expiresAt.getTime() - (typeof api?.getServerNow === 'function' ? api.getServerNow() : Date.now());

    stopCd = startCountdown(
      expiresAt.toISOString(),
      (secs) => {
        face.textContent = formatCountdown(secs);
        // Update progress bar
        if (progressBar && totalMs > 0) {
          const remaining = (secs * 1000) / totalMs;
          progressBar.style.width = `${Math.max(0, Math.min(100, remaining * 100))}%`;
        }
      },
      () => {
        stopCd = null;
        if (stopVisualAnim) { stopVisualAnim(); stopVisualAnim = null; }
        load();
      },   // when 5 min is up, re-poll normally
    );
  }
  // ── End instruction helpers ─────────────────────────────────────────────

  // ── In-Game Rules Modal Trigger ─────────────────────────────────────────
  let activeModalStopAnim = null;

  function openRulesModal() {
    let modalEl = document.getElementById('game-rules-modal');
    if (modalEl) { modalEl.remove(); }

    const instr = INSTRUCTIONS[opts.gameCode];
    if (!instr) return;

    const visual = getAnimatedVisual(opts.gameCode);
    const stepsHTML = instr.steps.map((s, i) => `
      <li style="--stagger-i:${i}">
        <div class="instr-step-num">${i + 1}</div>
        <div class="instr-step-text">
          <span class="en">${s.en}</span>
          <span class="jp">${s.jp}</span>
        </div>
      </li>
    `).join('');

    modalEl = document.createElement('div');
    modalEl.id = 'game-rules-modal';
    modalEl.className = 'rules-modal-overlay';
    modalEl.innerHTML = `
      <div class="rules-modal-dialog">
        <div class="rules-modal-header">
          <div class="rules-modal-title">
            <span class="jp">${instr.jp}</span>
            <span class="en">${instr.en}</span>
          </div>
          <button class="rules-modal-close" id="rules-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="rules-modal-body">
          <div class="instr-visual">
            ${visual.html}
          </div>
          <ol class="instr-steps">${stepsHTML}</ol>
        </div>
        <div class="rules-modal-footer">
          <button class="rules-modal-dismiss-btn" id="rules-modal-dismiss-btn" type="button">
            閉じる / Close Rules
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(modalEl);

    const visualContainer = modalEl.querySelector('.instr-visual');
    if (visualContainer) {
      activeModalStopAnim = visual.start(visualContainer);
    }

    function closeModal() {
      if (activeModalStopAnim) { activeModalStopAnim(); activeModalStopAnim = null; }
      modalEl.classList.remove('open');
      modalEl.classList.add('closing');
      setTimeout(() => { if (modalEl && modalEl.parentNode) modalEl.remove(); }, 240);
    }

    const closeBtn = modalEl.querySelector('#rules-modal-close');
    const dismissBtn = modalEl.querySelector('#rules-modal-dismiss-btn');
    if (closeBtn) closeBtn.onclick = closeModal;
    if (dismissBtn) dismissBtn.onclick = closeModal;
    modalEl.onclick = (e) => {
      if (e.target === modalEl) closeModal();
    };

    requestAnimationFrame(() => {
      modalEl.classList.add('open');
    });
  }

  load();
  return () => {
    disposed = true;
    if (stopCd) stopCd();
    if (stopVisualAnim) { stopVisualAnim(); stopVisualAnim = null; }
    if (activeModalStopAnim) { activeModalStopAnim(); activeModalStopAnim = null; }
    const modalEl = document.getElementById('game-rules-modal');
    if (modalEl) modalEl.remove();
    if (liveWs) liveWs.close();
    if (lbWs) lbWs.close();
    const appEl = document.getElementById('app');
    if (appEl) appEl.classList.remove('has-scoreboard');
  };
}