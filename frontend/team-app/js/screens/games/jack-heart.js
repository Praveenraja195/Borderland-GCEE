import { api } from '../../../../shared/js/api.js?v=v51_typewriter_scoreboard';
import { renderGameScreen } from './shell.js?v=v51_typewriter_scoreboard';
import { toast, startCountdown, formatCountdown } from '../../../../shared/js/ui.js?v=v51_typewriter_scoreboard';
import { translateError, demoNoteHTML } from '../../../../shared/js/copy.js?v=v51_typewriter_scoreboard';

const SUITS = [
  { code: 'SPADE', name: 'Spades', jpName: 'スペード', icon: '♠', startId: 1, isRed: false },
  { code: 'HEART', name: 'Hearts', jpName: 'ハート', icon: '♥', startId: 11, isRed: true },
  { code: 'DIAMOND', name: 'Diamonds', jpName: 'ダイヤ', icon: '♦', startId: 21, isRed: true },
  { code: 'CLUB', name: 'Clubs', jpName: 'クラブ', icon: '♣', startId: 31, isRed: false },
];

const RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10'];

/* ============================================================
   ROUND DETAIL — reads current/total round from ctx
   ------------------------------------------------------------
   Confirmed from shell.js: renderForSession() builds ctx with
   `roundNumber: targetRound.round_number` and `totalRounds`
   (session.rounds.length), so those are the real field names —
   this is the only place round position shows now that we hide
   shell.js's own .bracket-header (see hideShellChrome below).
   ============================================================ */
function getRoundLabel(ctx) {
  const current = ctx.roundNumber ?? null;
  const total = ctx.totalRounds ?? null;

  if (current != null && total != null) {
    return `JACK OF HEARTS — ROUND ${current}/${total}`;
  }
  if (current != null) {
    return `JACK OF HEARTS — ROUND ${current}`;
  }
  return 'JACK OF HEARTS';
}

// The shell hands us api.demo instead of api.team when a practice round is
// running (same method names, different endpoints — see shared/js/api.js).
function gameApi(ctx) {
  return ctx.gameApi || api.team;
}

function getCardInfo(symbolId) {
  if (!symbolId || symbolId < 1 || symbolId > 40) return null;
  const suitIndex = Math.floor((symbolId - 1) / 10);
  const rankIndex = (symbolId - 1) % 10;
  const suit = SUITS[suitIndex];
  const rank = RANKS[rankIndex];
  return {
    symbolId,
    suitCode: suit?.code,
    suitName: suit?.name,
    suitIcon: suit?.icon,
    isRed: suit?.isRed,
    rank,
    label: `${suit?.icon} ${rank}`,
    fullLabel: `${suit?.name} ${rank}`,
  };
}

export function renderJackHeart(root, navigate) {
  return renderGameScreen(root, navigate, {
    gameCode: 'JACK_HEART',
    apiGameCode: 'jack-heart',
    renderActive(container, ctx) {
      hideShellChrome(root, container);
      injectTheme();
      mountRound(container, ctx);
    },
  });
}

/* ============================================================
   FIX #1 — DUPLICATE HEADER / DUPLICATE TIMER FROM shell.js
   ------------------------------------------------------------
   Traced this against the real shell.js (renderGameScreen):

   - The top "【ラウンド】1/5 JACK OF HEARTS (Round 1/5)" block is
     `root.querySelector('.bracket-header')` — a single, stable
     DOM node shell.js creates once and updates via `.innerHTML`
     on every renderForSession() call. It's not recreated, so we
     only need to hide it once — no MutationObserver required.

   - The second "00:00:29 / TIME REMAINING" block is a
     `.countdown-wrap` div shell.js appends as a sibling of our
     container, right before it, ONLY when `ctx.deadline` exists
     (shell.js special-cases MINDMAZE to hide this itself — it
     never special-cased JACK_HEART, hence the duplicate). This
     wrapper IS recreated every time shell.js remounts the round
     (`body.innerHTML = ''` happens on every renderForSession），
     so we re-hide it each time renderActive runs — which is
     exactly when this function is called.
   ============================================================ */
function hideShellChrome(root, activeContainer) {
  const bracketHeader = root.querySelector('.bracket-header');
  if (bracketHeader) bracketHeader.style.display = 'none';

  // activeContainer (== the `container` div passed to renderActive)
  // is appended as a child of shell.js's local `container` var,
  // which also holds the sibling `.countdown-wrap` when present.
  const shellLocalContainer = activeContainer.parentElement;
  if (shellLocalContainer) {
    const cdWrap = shellLocalContainer.querySelector(':scope > .countdown-wrap');
    if (cdWrap) cdWrap.style.display = 'none';
  }
}

/* ============================================================
   THEME — Black & White, Photorealistic 3D Cards, Fully Responsive
   ============================================================ */
function injectTheme() {
  if (document.getElementById('jh-theme-styles')) return;
  const style = document.createElement('style');
  style.id = 'jh-theme-styles';
  style.textContent = `
  body > header, .game-header, .screen-header { display: none !important; }

  .jh-root {
    --bg: #ffffff;
    --fg: #000000;
    --card-base: #fbfbfb;
    --card-edge: #eaeaea;
    --card-border: #1a1a1a;
    --card-red: #df1a22; 
    
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    color: var(--fg);
    background: var(--bg);
    min-height: 100vh;
    padding: 12px 16px;
    animation: jhFadeIn .4s ease both;
    max-width: 500px;
    margin: 0 auto;
  }
  
  .jh-root * { box-sizing: border-box; }
  @keyframes jhFadeIn { from{ opacity:0; } to{ opacity:1; } }

  .suit-red { color: var(--card-red) !important; }
  .suit-black { color: var(--fg) !important; }

  .jh-custom-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 20px;
    padding-bottom: 16px;
    border-bottom: 2px solid var(--fg);
  }
  .jh-ch-left { display: flex; flex-direction: column; gap: 4px; justify-content: center; }
  .jh-ch-title { font-size: 1.05rem; font-weight: 900; text-transform: uppercase; letter-spacing: 0.03em; color: var(--fg); }
  .jh-ch-round { font-size: 0.75rem; font-weight: 800; text-transform: uppercase; color: #666; letter-spacing: 0.05em; }

  .jh-ch-right { display: flex; flex-direction: column; align-items: flex-end; }
  .jh-timer-label { font-size: 0.65rem; font-weight: 800; text-transform: uppercase; color: #666; margin-bottom: 4px; }
  .jh-timer-box { 
    border: 2px solid var(--fg); 
    border-radius: 8px; 
    padding: 6px 12px; 
    font-size: 1.4rem; 
    font-weight: 900; 
    box-shadow: 3px 3px 0px var(--fg); 
    font-variant-numeric: tabular-nums;
    background: var(--bg);
  }
  .jh-timer-box.danger { color: var(--card-red); border-color: var(--card-red); box-shadow: 3px 3px 0px var(--card-red); }

  .jh-arena, .jh-vault {
    background: var(--bg);
    border: 2px solid var(--fg);
    padding: 18px;
    margin-bottom: 20px;
    position: relative;
    box-shadow: 4px 4px 0px var(--fg);
  }

  .jh-tray-toggle {
    width: 100%; display: flex; align-items: center; justify-content: space-between;
    background: var(--bg); border: 2px solid var(--fg); padding: 12px 16px;
    cursor: pointer; transition: all .2s ease; color: var(--fg); font-family: inherit;
    font-weight: 900; text-transform: uppercase; letter-spacing: 0.06em;
  }
  .jh-tray-toggle:hover { background: var(--fg); color: var(--bg); }
  .jh-tray-toggle .tt-left { display: flex; align-items: center; gap: 12px; }
  .jh-tray-toggle .tt-title-text { font-size: 0.95rem; }
  .jh-tray-toggle .tt-count {
    font-size: 0.75rem; font-weight: 900; background: var(--fg); color: var(--bg);
    padding: 2px 8px; border-radius: 12px;
  }
  .jh-tray-toggle:hover .tt-count { background: var(--bg); color: var(--fg); }
  
  .jh-tray { overflow: hidden; max-height: 0; opacity: 0; transition: all .35s ease; }
  .jh-tray.open { max-height: 2000px; opacity: 1; margin-top: 16px; }
  .jh-tray-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); gap: 12px; }

  .jh-flip-outer { perspective: 1000px; }
  .jh-flip-card {
    width: 100%; aspect-ratio: 2.5/3.5; position: relative; cursor: pointer;
    transform-style: preserve-3d; transition: transform .6s cubic-bezier(0.23, 1, 0.32, 1);
  }
  .jh-flip-card.flipped { transform: rotateY(180deg); }
  .jh-flip-face {
    position: absolute; inset: 0; backface-visibility: hidden; 
    border-radius: 6px; border: 2px solid var(--fg); background: var(--card-base);
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 6px; text-align: center;
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
  }
  
  .jh-flip-face.front {
    background: repeating-linear-gradient(45deg, rgba(0,0,0,0.04) 0, rgba(0,0,0,0.04) 2px, transparent 2px, transparent 6px), var(--card-base);
  }
  .back-team-label { font-size: 0.55rem; font-weight: 700; color: #666; text-transform: uppercase; margin-bottom: 2px; }
  .back-team { font-size: 0.7rem; font-weight: 900; text-transform: uppercase; margin-bottom: 8px; word-break: break-all; color: var(--fg); line-height: 1.2; }
  .back-suit-badge { border: 1.5px solid currentColor; padding: 2px 6px; font-weight: 800; font-size: 0.65rem; border-radius: 4px; }

  .jh-flip-face.back {
    transform: rotateY(180deg);
    background: linear-gradient(145deg, #ffffff 0%, #f4f4f4 100%);
    border: 1px solid var(--card-edge);
    justify-content: space-between;
  }
  .jh-flip-face.back::before {
    content: ''; position: absolute; inset: 4px;
    border: 1px solid rgba(0,0,0,0.08); border-radius: 4px; pointer-events: none;
  }

  .jh-team-suit-badge {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    background: #f8fafc;
    border: 2px solid var(--fg);
    border-radius: 10px;
    padding: 10px 16px;
    margin: 0 auto 20px;
    box-shadow: 2px 2px 0px var(--fg);
    max-width: 320px;
  }
  .jh-badge-label {
    font-size: 0.72rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #64748b;
  }
  .jh-badge-suit {
    font-size: 1.05rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .jh-chosen-text {
    text-align: center; font-size: 0.85rem; font-weight: 800; text-transform: uppercase;
    letter-spacing: 0.1em; margin-bottom: 16px; line-height: 1.4;
  }

  .jh-carousel-stage {
    perspective: 1200px;
    display: flex; align-items: center; justify-content: center; gap: 32px;
    margin: 0 auto 24px;
    padding: 10px 0;
  }
  .jh-nav-btn {
    background: var(--bg); border: 2px solid var(--fg); border-radius: 50%;
    width: 48px; height: 48px; font-size: 1.2rem; font-weight: 900; cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: all .2s ease; color: var(--fg);
    box-shadow: 2px 2px 0px var(--fg);
    flex-shrink: 0; z-index: 10;
  }
  .jh-nav-btn:hover { background: var(--fg); color: var(--bg); transform: scale(1.05); }
  .jh-nav-btn:active { transform: translate(2px, 2px); box-shadow: none; }

  .jh-card-wrapper {
    width: 175px; height: 254px;
    position: relative;
    transform-style: preserve-3d;
    flex-shrink: 0;
  }
  
  .jh-big-card {
    width: 100%; height: 100%;
    background: linear-gradient(145deg, #ffffff 0%, #f4f4f4 100%);
    border: 1px solid var(--card-edge);
    border-radius: 12px;
    position: relative;
    overflow: hidden;
    cursor: pointer;
    display: flex; flex-direction: column; justify-content: space-between;
    padding: 10px;
    box-shadow:
      0 1px 2px rgba(0,0,0,0.06),
      0 8px 16px -4px rgba(0,0,0,0.12),
      0 20px 32px -8px rgba(0,0,0,0.16),
      0 0 0 1px rgba(0,0,0,0.08) inset;
    transition: transform 0.25s ease, box-shadow 0.25s ease;
  }

  .jh-big-card::before {
    content: ''; position: absolute; inset: 5px;
    border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; pointer-events: none;
  }

  .jh-big-card .card-sheen {
    content: ''; position: absolute; inset: 0;
    background: linear-gradient(115deg, transparent 20%, rgba(255,255,255,0.7) 45%, rgba(255,255,255,0.9) 50%, transparent 60%);
    opacity: 0.6; transform: translateX(-100%); pointer-events: none; z-index: 5;
  }

  .jh-big-card.slide-next { animation: jhSlideNext 0.35s cubic-bezier(0.2, 0.8, 0.25, 1) both; }
  .jh-big-card.slide-prev { animation: jhSlidePrev 0.35s cubic-bezier(0.2, 0.8, 0.25, 1) both; }

  @keyframes jhSlideNext {
    0% { transform: translateX(20%) rotateY(-20deg) scale(0.92); opacity: 0.4; }
    50% { transform: translateX(-5%) rotateY(4deg) scale(1.02); opacity: 1; }
    100% { transform: translateX(0) rotateY(0deg) scale(1); opacity: 1; }
  }
  @keyframes jhSlidePrev {
    0% { transform: translateX(-20%) rotateY(20deg) scale(0.92); opacity: 0.4; }
    50% { transform: translateX(5%) rotateY(-4deg) scale(1.02); opacity: 1; }
    100% { transform: translateX(0) rotateY(0deg) scale(1); opacity: 1; }
  }

  .jh-big-card.slide-next .card-sheen,
  .jh-big-card.slide-prev .card-sheen { animation: jhSheenSweep 0.5s ease forwards; }
  @keyframes jhSheenSweep { 0% { transform: translateX(-120%); } 100% { transform: translateX(140%); } }

  .jh-big-card:hover { transform: translateY(-4px); box-shadow: 0 12px 24px -4px rgba(0,0,0,0.18), 0 28px 42px -10px rgba(0,0,0,0.22), 0 0 0 1px rgba(0,0,0,0.1) inset; }
  .jh-big-card:hover .card-sheen { transition: transform 0.6s ease; transform: translateX(120%); }

  .jh-big-card.is-chosen { box-shadow: 0 0 0 3px var(--fg), 0 16px 32px -4px rgba(0,0,0,0.25); }

  .pip-corner { display: flex; flex-direction: column; align-items: center; line-height: 0.9; font-weight: 900; z-index: 1; user-select: none; color: inherit; }
  .pip-corner.bottom { align-self: flex-end; transform: rotate(180deg); }
  .pip-center { position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); z-index: 0; line-height: 1; filter: drop-shadow(0 2px 4px rgba(0,0,0,0.08)); user-select: none; color: inherit; }

  .jh-big-card .pip-corner { font-size: 1.4rem; }
  .jh-big-card .pip-corner .mini-suit { font-size: 1rem; margin-top: 4px; }
  .jh-big-card .pip-center { font-size: 4.5rem; }

  .jh-flip-face.back .pip-corner { font-size: 1.05rem; }
  .jh-flip-face.back .pip-corner .mini-suit { font-size: 0.8rem; margin-top: 2px; }
  .jh-flip-face.back .pip-center { font-size: 3rem; }

  .jh-confirm-btn {
    display: block; width: 100%; margin: 0 auto;
    background: var(--bg); color: var(--fg); border: 2px solid var(--fg); padding: 14px;
    font-size: 1rem; font-weight: 900; text-transform: uppercase; letter-spacing: 0.05em; cursor: pointer;
    transition: all 0.2s cubic-bezier(0.2, 0.8, 0.2, 1); box-shadow: 4px 4px 0px var(--fg);
  }
  .jh-confirm-btn:hover:not(.is-selected) { background: #f0f0f0; transform: translateY(-2px); box-shadow: 6px 6px 0px var(--fg); }
  .jh-confirm-btn:active:not(.is-selected) { transform: translate(2px, 2px); box-shadow: 2px 2px 0px var(--fg); }
  .jh-confirm-btn.is-selected { background: var(--fg); color: var(--bg); cursor: default; box-shadow: none; transform: none; pointer-events: none; }

  .jh-result { text-align: center; padding: 40px 18px; border: 4px solid var(--fg); background: var(--bg); }
  .jh-result-badge { display: inline-block; font-weight: 900; text-transform: uppercase; font-size: 1.2rem; border-bottom: 2px solid var(--fg); padding-bottom: 4px; margin-bottom: 16px; }
  .jh-result-desc { font-size: 1rem; font-weight: 600; margin-bottom: 24px; }
  .jh-result-score { font-size: 4rem; font-weight: 900; }

  @media (max-width: 380px) {
    .jh-root { padding: 8px; }
    .jh-carousel-stage { gap: 16px; }
    .jh-nav-btn { width: 40px; height: 40px; font-size: 1.1rem; }
    .jh-card-wrapper { width: 150px; height: 218px; }
    .jh-big-card .pip-center { font-size: 3.8rem; }
    .jh-suit-grid { gap: 6px; }
    .jh-suit-btn { padding: 10px 0; font-size: 1.5rem; }
    .jh-suit-btn span { font-size: 0.65rem; }
  }
  `;
  document.head.appendChild(style);
}

async function mountRound(container, ctx) {
  container.className = 'jh-root';

  if (ctx.isClosed) {
    const scoreVal = Number(ctx.score);
    const isPositive = !isNaN(scoreVal) && scoreVal > 0;
    const formattedScore = isPositive ? `+${scoreVal.toFixed(1)}` : `0.0`;

    container.innerHTML = `
      <div class="jh-result">
        <div class="jh-result-badge">
          ${ctx.isDemo ? 'PRACTICE — ' : ''}${isPositive ? 'MATCH FOUND' : 'ROUND CLOSED'}
        </div>
        ${demoNoteHTML(ctx.isDemo)}
        <p class="jh-result-desc">
          ${isPositive ? 'You successfully identified your hidden card.' : 'No match this round.'}
        </p>
        <div class="jh-result-score">${formattedScore}</div>
      </div>
    `;
    return;
  }

  let symbols = [];
  let mySuitInfo = null;
  try {
    const [visSyms, suitRes] = await Promise.all([
      gameApi(ctx).jackHeartVisibleSymbols(ctx.roundId),
      gameApi(ctx).jackHeartMySuit(ctx.roundId).catch(() => null),
    ]);
    symbols = visSyms || [];
    mySuitInfo = suitRes;
  } catch (err) {
    container.innerHTML = `<p style="font-weight:bold;">Error: ${err.message}</p>`;
    return;
  }

  // Fallback 1: check active round selection
  if (!mySuitInfo || !mySuitInfo.suit_code) {
    try {
      const activeRound = await api.team.getActiveRound().catch(() => null);
      const rId = ctx.session?.round_id || activeRound?.round_id;
      if (rId) {
        const sel = await api.team.mySelection(rId).catch(() => null);
        if (sel && sel.suit_code) {
          mySuitInfo = { suit_code: sel.suit_code };
        }
      }
    } catch (_) { }
  }

  // Fallback 2: check localStorage
  if (!mySuitInfo || !mySuitInfo.suit_code) {
    const localSuit = localStorage.getItem('bl_team_suit') || localStorage.getItem('bl_suit');
    if (localSuit) {
      mySuitInfo = { suit_code: localSuit };
    }
  }

  // Cache verified suit in localStorage for offline/fast load
  if (mySuitInfo?.suit_code) {
    localStorage.setItem('bl_team_suit', mySuitInfo.suit_code.toUpperCase());
  }

  // Determine team suit strictly from API assignment
  let selectedSuitIdx = 0;
  const suitCode = (mySuitInfo?.suit_code || '').toUpperCase();
  if (suitCode) {
    const sIdx = SUITS.findIndex((s) => s.code === suitCode);
    if (sIdx !== -1) selectedSuitIdx = sIdx;
  }

  const activeSuit = SUITS[selectedSuitIdx];
  let selectedRankIdx = null;
  let selectedSymbolId = null;

  let viewingRankIdx = 0;
  let slideDirection = null;
  let trayOpen = false;
  let saving = false;
  const flippedIds = new Set();

  try {
    const saved = localStorage.getItem(`bl_jh_selected_${ctx.roundId}`);
    if (saved) {
      const sid = Number(saved);
      if (sid >= activeSuit.startId && sid < activeSuit.startId + 10) {
        selectedSymbolId = sid;
        selectedRankIdx = sid - activeSuit.startId;
        viewingRankIdx = selectedRankIdx;
      }
    }
  } catch (_) { }

  async function saveSelection(symbolId) {
    if (!symbolId || saving) return;
    saving = true;
    try {
      localStorage.setItem(`bl_jh_selected_${ctx.roundId}`, String(symbolId));
    } catch (_) { }

    try {
      await gameApi(ctx).jackHeartSubmit(ctx.roundId, symbolId);
      const card = getCardInfo(symbolId);
      toast(`✓ Saved: ${card?.fullLabel}`, { duration: 1800 });
    } catch (err) {
      console.warn('Auto-save error:', err);
    } finally {
      saving = false;
    }
  }

  function renderBoard() {
    const viewRankLabel = RANKS[viewingRankIdx];

    const currentViewSymbolId = activeSuit.startId + viewingRankIdx;
    const isCurrentlyViewedCardChosen = (selectedSymbolId === currentViewSymbolId);

    let chosenText = "NONE";
    if (selectedSymbolId) {
      const card = getCardInfo(selectedSymbolId);
      chosenText = card.fullLabel;
    }

    container.innerHTML = `
      <div class="jh-custom-header">
        <div class="jh-ch-left">
          <div class="jh-ch-title">Jack of Hearts</div>
          <div class="jh-ch-round">${getRoundLabel(ctx)}</div>
        </div>
        <div class="jh-ch-right">
          <div class="jh-timer-label">TIME REMAINING</div>
          <div class="jh-timer-box" id="jh-timer">--:--</div>
        </div>
      </div>

      <div class="jh-arena">
        <button type="button" id="tray-toggle" class="jh-tray-toggle">
          <div class="tt-left">
            <span class="tt-title-text">TABLE CARDS</span>
            <span class="tt-count">${symbols.length}</span>
          </div>
          <span class="tt-chev" style="transform: rotate(${trayOpen ? '180deg' : '0'})">▼</span>
        </button>
        <div class="jh-tray ${trayOpen ? 'open' : ''}" id="tray-panel">
          <div style="font-size:0.75rem; font-weight:bold; margin-bottom:12px; text-transform:uppercase;">Tap cards to flip them over</div>
          <div class="jh-tray-grid" id="tray-grid"></div>
        </div>
      </div>

      <div class="jh-vault">
        <div class="jh-team-suit-badge ${activeSuit.isRed ? 'suit-red' : 'suit-black'}">
          <span class="jh-badge-label">YOUR SUIT:</span>
          <span class="jh-badge-suit">${activeSuit.icon} ${activeSuit.name.toUpperCase()} (${activeSuit.jpName})</span>
        </div>

        <div class="jh-chosen-text">
          CHOSEN: <span style="border-bottom: 2px solid #000; padding-bottom:2px;">${chosenText.toUpperCase()}</span>
        </div>

        <div class="jh-carousel-stage">
          <button type="button" class="jh-nav-btn" id="btn-prev" aria-label="Previous card">❮</button>
          
          <div class="jh-card-wrapper">
            <div class="jh-big-card ${activeSuit.isRed ? 'suit-red' : 'suit-black'} ${isCurrentlyViewedCardChosen ? 'is-chosen' : ''} ${slideDirection || ''}" id="big-card">
              <div class="card-sheen"></div>
              <div class="pip-corner">
                <span>${viewRankLabel}</span>
                <span class="mini-suit">${activeSuit.icon}</span>
              </div>
              <div class="pip-center">${activeSuit.icon}</div>
              <div class="pip-corner bottom">
                <span>${viewRankLabel}</span>
                <span class="mini-suit">${activeSuit.icon}</span>
              </div>
            </div>
          </div>
          
          <button type="button" class="jh-nav-btn" id="btn-next" aria-label="Next card">❯</button>
        </div>
        
        <button type="button" class="jh-confirm-btn ${isCurrentlyViewedCardChosen ? 'is-selected' : ''}" id="btn-confirm">
          ${isCurrentlyViewedCardChosen ? '✓ CHOSEN' : `SELECT ${viewRankLabel} OF ${activeSuit.name.toUpperCase()}`}
        </button>
      </div>
    `;

    // The countdown (started once below, outside renderBoard) keeps
    // running independently of re-renders. #jh-timer gets recreated
    // by the innerHTML replacement above, so we immediately paint the
    // last known value here to avoid a "--:--" flash until the next
    // tick — see the shared startCountdown() call at the bottom of
    // mountRound for the actual ticking logic.
    paintTimer();

    slideDirection = null;

    const trayToggleBtn = container.querySelector('#tray-toggle');
    trayToggleBtn.addEventListener('click', () => {
      trayOpen = !trayOpen;
      renderBoard();
    });

    const trayGrid = container.querySelector('#tray-grid');
    if (symbols && symbols.length > 0) {
      symbols.forEach((s, i) => {
        const cardInfo = getCardInfo(s.symbol_id);
        const cardIcon = cardInfo ? cardInfo.suitIcon : (s.symbol_code.includes('HEART') ? '♥' : s.symbol_code.includes('DIAMOND') ? '♦' : s.symbol_code.includes('CLUB') ? '♣' : '♠');
        const cardRank = cardInfo ? cardInfo.rank : (s.rank || s.symbol_label.replace(/[^0-9A]/g, ''));

        const isCardRed = (cardInfo && cardInfo.isRed) || s.symbol_code.includes('HEART') || s.symbol_code.includes('DIAMOND');
        const teamSuitSym = s.team_suit_symbol || (s.team_suit_code === 'HEART' ? '♥' : s.team_suit_code === 'DIAMOND' ? '♦' : s.team_suit_code === 'CLUB' ? '♣' : s.team_suit_code === 'SPADE' ? '♠' : '');
        const isTeamSuitRed = s.team_suit_code === 'HEART' || s.team_suit_code === 'DIAMOND';

        const symbolKey = String(s.symbol_id) + '_' + i;
        const isFlipped = flippedIds.has(symbolKey);

        const outer = document.createElement('div');
        outer.className = 'jh-flip-outer';

        outer.innerHTML = `
          <div class="jh-flip-card ${isFlipped ? 'flipped' : ''}" data-key="${symbolKey}">
            <div class="jh-flip-face front">
              <div class="back-team-label">Team</div>
              <div class="back-team">${s.team_name || s.team_code}</div>
              ${teamSuitSym ? `<div class="back-suit-badge ${isTeamSuitRed ? 'suit-red' : 'suit-black'}">${teamSuitSym} ${s.team_suit_code || ''}</div>` : ''}
            </div>
            
            <div class="jh-flip-face back ${isCardRed ? 'suit-red' : 'suit-black'}">
              <div class="pip-corner">
                <span>${cardRank}</span>
                <span class="mini-suit">${cardIcon}</span>
              </div>
              <div class="pip-center">${cardIcon}</div>
              <div class="pip-corner bottom">
                <span>${cardRank}</span>
                <span class="mini-suit">${cardIcon}</span>
              </div>
            </div>
          </div>
        `;

        const flipEl = outer.querySelector('.jh-flip-card');
        flipEl.addEventListener('click', () => {
          const nowFlipped = flipEl.classList.toggle('flipped');
          if (nowFlipped) flippedIds.add(symbolKey);
          else flippedIds.delete(symbolKey);
        });
        trayGrid.appendChild(outer);
      });
    } else {
      trayGrid.innerHTML = `<div style="font-size:0.8rem; font-weight:bold; padding: 12px 0;">NO CARDS ON TABLE YET.</div>`;
    }

    const btnPrev = container.querySelector('#btn-prev');
    const btnNext = container.querySelector('#btn-next');
    const btnConfirm = container.querySelector('#btn-confirm');
    const bigCard = container.querySelector('#big-card');

    btnPrev.addEventListener('click', () => {
      viewingRankIdx = (viewingRankIdx - 1 + 10) % 10;
      slideDirection = 'slide-prev';
      renderBoard();
    });

    btnNext.addEventListener('click', () => {
      viewingRankIdx = (viewingRankIdx + 1) % 10;
      slideDirection = 'slide-next';
      renderBoard();
    });

    const handleSelect = () => {
      if (isCurrentlyViewedCardChosen) return;
      selectedRankIdx = viewingRankIdx;
      selectedSymbolId = activeSuit.startId + selectedRankIdx;
      saveSelection(selectedSymbolId);
      renderBoard();
    };

    btnConfirm.addEventListener('click', handleSelect);
    bigCard.addEventListener('click', handleSelect);
  }

  /* ============================================================
     FIX #2 — COUNTDOWN TIMER LOGIC
     ------------------------------------------------------------
     Problems in the original:
       1. startTimer() was called from *inside* renderBoard(), and
          renderBoard() runs on every single UI interaction (suit
          click, prev/next, tray toggle). Each call did
          clearInterval + setInterval again, so the countdown was
          being torn down and rebuilt constantly instead of ticking
          steadily, and briefly showed "--:--" after every click.
       2. It hand-rolled `new Date(deadline).getTime() - Date.now()`
          against the *client's* clock. shell.js already has a
          vetted `startCountdown(deadline, onTick, onDone)` in
          ui.js — the exact function driving the (now-hidden)
          shell timer everywhere else in the app — so reinventing
          the math here was itself a bug risk: any clock-skew or
          server-time correction that utility handles would NOT
          have applied to our duplicate, hand-rolled timer.

     Fix: delegate entirely to the shared startCountdown/
     formatCountdown, same as shell.js. It's started exactly once
     per round mount, writes the value immediately (no blank
     flash), and paintTimer() (called from renderBoard) just
     re-applies the latest known value to whichever #jh-timer node
     currently exists — safe because it's a pure lookup + write,
     never a stale reference held across renders.
     ============================================================ */
  let lastSecs = null;
  let stopCd = null;

  function paintTimer() {
    const el = container.querySelector('#jh-timer');
    if (!el) return;
    if (lastSecs === null) {
      el.textContent = '--:--';
      return;
    }
    el.textContent = formatCountdown(lastSecs);
    el.classList.toggle('danger', lastSecs <= 60);
  }

  function startTimerOnce() {
    if (!ctx.deadline) return; // no deadline from API — stays "--:--"
    stopCd = startCountdown(
      ctx.deadline,
      (secs) => { lastSecs = secs; paintTimer(); },
      () => { lastSecs = 0; paintTimer(); },
    );
  }

  renderBoard();
  startTimerOnce();
}