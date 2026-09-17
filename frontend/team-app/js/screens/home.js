import { api, getToken } from '../../../shared/js/api.js';
import { GAMES, HEADERS } from '../../../shared/js/copy.js';
import { suitIconSVG } from '../../../shared/js/suit-icons.js';

const NAV_ICONS = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>',
  trophy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
};

import { toast } from '../../../shared/js/ui.js';

function safeVibrate(pattern) {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      if (!navigator.userActivation || navigator.userActivation.hasBeenActive) {
        navigator.vibrate(pattern);
      }
    }
  } catch (_) {}
}

export function showCameraLockedModal() {
  const existing = document.getElementById('camera-locked-modal');
  if (existing) existing.remove();

  // Trigger mobile haptic vibration safely
  safeVibrate([60, 50, 60]);

  // Also trigger toast notification
  toast('⚠️ Only accessible when you are alive after all games finished on Round 1.', { error: true, duration: 4000 });

  const modal = document.createElement('div');
  modal.id = 'camera-locked-modal';
  modal.className = 'bl-warn-popup-overlay';
  modal.innerHTML = `
    <div class="bl-warn-popup-card">
      <div class="bl-warn-icon-box">
        <svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
          <circle cx="12" cy="13" r="4"/>
          <line x1="1" y1="1" x2="23" y2="23" stroke="var(--bl-red)" stroke-width="2.5"/>
        </svg>
      </div>

      <div class="bl-warn-title-jp">アクセス制限</div>
      <div class="bl-warn-title-en">ACCESS RESTRICTED</div>

      <div class="bl-warn-message-box">
        <div class="bl-warn-message-jp">
          第1ラウンドの全ゲーム終了後、生存している場合のみアクセス可能です。
        </div>
        <div class="bl-warn-message-en">
          Only accessible when you are alive after all the games finished on Round 1.
        </div>
      </div>

      <button class="bl-warn-btn-close" id="camera-modal-close" type="button">
        確認 / UNDERSTOOD
      </button>
    </div>
  `;

  document.body.appendChild(modal);

  const closeBtn = modal.querySelector('#camera-modal-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      modal.remove();
    });
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.remove();
  });
}

import { startCountdown } from '../../../shared/js/ui.js';
import { LiveChannel } from '../../../shared/js/ws.js';

export function triggerLaserEliminationSequence() {
  const existing = document.getElementById('laser-elimination-overlay');
  if (existing) return;

  // Synthesize realistic high-voltage laser blast + electrical crackle + heavy sub-bass boom
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    
    // 1. High frequency laser chirp
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sawtooth';
    osc1.frequency.setValueAtTime(2200, ctx.currentTime);
    osc1.frequency.exponentialRampToValueAtTime(110, ctx.currentTime + 0.38);
    gain1.gain.setValueAtTime(1.0, ctx.currentTime);
    gain1.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.42);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start();
    osc1.stop(ctx.currentTime + 0.42);

    // 2. White noise electrical sizzle/discharge
    const bufferSize = Math.floor(ctx.sampleRate * 0.5);
    const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < bufferSize; i++) {
      data[i] = Math.random() * 2 - 1;
    }
    const noise = ctx.createBufferSource();
    noise.buffer = buffer;
    const noiseFilter = ctx.createBiquadFilter();
    noiseFilter.type = 'bandpass';
    noiseFilter.frequency.setValueAtTime(1400, ctx.currentTime);
    noiseFilter.frequency.exponentialRampToValueAtTime(250, ctx.currentTime + 0.5);
    const noiseGain = ctx.createGain();
    noiseGain.gain.setValueAtTime(0.75, ctx.currentTime);
    noiseGain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.5);
    noise.connect(noiseFilter);
    noiseFilter.connect(noiseGain);
    noiseGain.connect(ctx.destination);
    noise.start();
    noise.stop(ctx.currentTime + 0.5);

    // 3. Deep visceral sub-bass boom
    setTimeout(() => {
      try {
        const osc2 = ctx.createOscillator();
        const gain2 = ctx.createGain();
        osc2.type = 'sine';
        osc2.frequency.setValueAtTime(170, ctx.currentTime);
        osc2.frequency.exponentialRampToValueAtTime(24, ctx.currentTime + 1.4);
        gain2.gain.setValueAtTime(1.0, ctx.currentTime);
        gain2.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 1.4);
        osc2.connect(gain2);
        gain2.connect(ctx.destination);
        osc2.start();
        osc2.stop(ctx.currentTime + 1.4);
      } catch (_) {}
    }, 100);
  } catch (_) {}

  // Mobile haptic vibration safely
  safeVibrate([250, 100, 350, 100, 900]);

  const overlay = document.createElement('div');
  overlay.id = 'laser-elimination-overlay';
  overlay.className = 'bl-laser-overlay';
  overlay.innerHTML = `
    <!-- Searing Alice in Borderland Sky Laser Beam -->
    <div class="bl-laser-beam">
      <div class="bl-laser-core"></div>
      <div class="bl-laser-corona"></div>
      <div class="bl-laser-flare"></div>
    </div>

    <!-- Blinding flash on impact -->
    <div class="bl-screen-flash"></div>
  `;

  document.body.appendChild(overlay);

  // After laser + flash finish (~1.2s), transition to broken screen video
  setTimeout(() => {
    // Remove laser beam and flash elements
    const beam = overlay.querySelector('.bl-laser-beam');
    const flash = overlay.querySelector('.bl-screen-flash');
    if (beam) beam.remove();
    if (flash) flash.remove();

    // Create and play the broken screen video (loops forever)
    const videoContainer = document.createElement('div');
    videoContainer.className = 'bl-broken-video-container';
    videoContainer.innerHTML = `
      <video class="bl-broken-video" autoplay playsinline muted loop>
        <source src="../shared/video/broken_video.mp4" type="video/mp4" />
      </video>
      <div class="bl-screen-blackout bl-gameover-hidden">
        <div class="bl-gameover-title" data-text="GAME OVER">GAME OVER</div>
      </div>
    `;
    overlay.appendChild(videoContainer);

    // Show GAME OVER message over the looping video after a brief delay
    const gameoverScreen = videoContainer.querySelector('.bl-screen-blackout');
    setTimeout(() => {
      gameoverScreen.classList.remove('bl-gameover-hidden');
      gameoverScreen.classList.add('bl-gameover-visible');
    }, 500);
  }, 1200);
}

function playVictoryFanfare() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const chords = [
      { freq: 440.00, time: 0.0, dur: 0.16 }, // A4
      { freq: 554.37, time: 0.14, dur: 0.16 }, // C#5
      { freq: 659.25, time: 0.28, dur: 0.20 }, // E5
      { freq: 880.00, time: 0.44, dur: 0.9 }, // A5 (triumphant climax)
    ];
    chords.forEach(({ freq, time, dur }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, ctx.currentTime + time);
      gain.gain.setValueAtTime(0, ctx.currentTime + time);
      gain.gain.linearRampToValueAtTime(0.35, ctx.currentTime + time + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + time + dur);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + time);
      osc.stop(ctx.currentTime + time + dur);
    });
  } catch (_) {}
}

function triggerCelebrationConfetti() {
  const container = document.createElement('div');
  container.className = 'bl-confetti-container';
  const colors = ['#10b981', '#34d399', '#f59e0b', '#fbbf24', '#ffffff', '#6ee7b7'];
  for (let i = 0; i < 45; i++) {
    const piece = document.createElement('div');
    piece.className = 'bl-confetti-piece';
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.backgroundColor = colors[Math.floor(Math.random() * colors.length)];
    piece.style.animationDelay = `${Math.random() * 0.8}s`;
    piece.style.animationDuration = `${1.8 + Math.random() * 1.5}s`;
    piece.style.transform = `scale(${0.6 + Math.random() * 0.8}) rotate(${Math.random() * 360}deg)`;
    container.appendChild(piece);
  }
  document.body.appendChild(container);
  setTimeout(() => container.remove(), 4500);
}

export async function showVisaModal(opts = {}) {
  const existing = document.getElementById('visa-app-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'visa-app-modal';
  modal.className = 'bl-warn-popup-overlay';
  modal.innerHTML = `
    <div class="visa-card-container">
      <div class="spinner" style="margin: 60px auto;"></div>
    </div>
  `;
  document.body.appendChild(modal);

  let stopCountdown = null;

  function closeModal() {
    if (stopCountdown) stopCountdown();
    modal.remove();
  }

  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeModal();
  });

  try {
    const roomId = localStorage.getItem('bl_room_id');
    const [team, activeRound, lb] = await Promise.all([
      api.team.me().catch(() => null),
      api.team.getActiveRound().catch(() => null),
      roomId ? api.team.roomLeaderboard(roomId).catch(() => []) : Promise.resolve([]),
    ]);

    let selection = null;
    if (activeRound?.round_id) {
      selection = await api.team.mySelection(activeRound.round_id).catch(() => null);
    }

    const teamName = team?.team_name || 'UNKNOWN TEAM';
    const teamCode = team?.team_code || 'T—';

    // Suit resolution
    const SUIT_DATA = {
      SPADE: { symbol: '♠', color: '#ffffff' },
      HEART: { symbol: '♥', color: '#D5262B' },
      DIAMOND: { symbol: '♦', color: '#D5262B' },
      CLUB: { symbol: '♣', color: '#ffffff' },
    };

    let suitCode = (selection?.suit_code || localStorage.getItem('bl_team_suit') || localStorage.getItem('bl_suit') || 'NONE').toUpperCase();
    let suitSymbol = selection?.suit_symbol || (SUIT_DATA[suitCode] ? SUIT_DATA[suitCode].symbol : '—');
    const isRedSuit = suitCode === 'HEART' || suitCode === 'DIAMOND';
    const suitDisplayColor = isRedSuit ? '#D5262B' : '#ffffff';

    const roomCode = selection?.room_code || localStorage.getItem('bl_room_code') || (localStorage.getItem('bl_room_id') ? 'ASSIGNED' : '—');

    // Check qualification from room leaderboard
    const myEntry = opts.myEntry || (lb || []).find(e => e.team_code === teamCode);
    const isResultsPublished = opts.isQualifiedNotice ? true : (myEntry ? myEntry.is_published : false);
    const isQualifiedForR2 = (isResultsPublished && myEntry?.is_qualified === true) || Boolean(opts.isQualifiedNotice);

    if (isQualifiedForR2) {
      playVictoryFanfare();
      triggerCelebrationConfetti();
      safeVibrate([150, 80, 150, 80, 400]);
    }

    modal.innerHTML = `
      <div class="visa-card-container ${isQualifiedForR2 ? 'qualified-glow animated-card' : ''}">
        ${isQualifiedForR2 ? `
          <div class="visa-extension-stamp">
            <span class="stamp-en">EXTENDED</span>
            <span class="stamp-jp">延長</span>
            <span class="stamp-sub">ROUND 2 QUALIFIED</span>
          </div>
        ` : ''}

        <!-- Top Watermark & Government Seal Header -->
        <div class="visa-card-topbar">
          <div class="visa-gov-tag">
            <span class="jp">今際の国 滞在許可証</span>
            <span class="en">IMMIGRATION BUREAU OF BORDERLAND</span>
          </div>
          <div class="visa-gothic-badge">V</div>
        </div>

        ${isQualifiedForR2 ? `
          <!-- Congratulations Qualified Banner -->
          <div class="visa-qualified-banner animated-banner">
            <div class="vqb-title">🎉 おめでとうございます！ / CONGRATULATIONS!</div>
            <div class="vqb-msg">
              <strong>VISA EXTENDED FOR ROUND 2</strong><br>
              第2ラウンドへの進出が決定しました。
            </div>
          </div>
        ` : ''}

        <!-- Participant Information Grid -->
        <div class="visa-bio-grid">
          <div class="visa-bio-cell full-width">
            <span class="visa-label">TEAM NAME / チーム名</span>
            <span class="visa-value highlight">${teamName}</span>
          </div>

          <div class="visa-bio-cell">
            <span class="visa-label">TEAM ID / 識別番号</span>
            <span class="visa-value mono">${teamCode}</span>
          </div>

          <div class="visa-bio-cell">
            <span class="visa-label">ASSIGNED SUIT / 絵柄</span>
            <span class="visa-value" style="color: ${suitDisplayColor}; font-weight: 900;">
              ${suitSymbol} ${suitCode !== 'NONE' ? suitCode : '—'}
            </span>
          </div>

          <div class="visa-bio-cell full-width">
            <span class="visa-label">ASSIGNED ROOM / 指定ルーム</span>
            <span class="visa-value mono">${roomCode !== '—' ? roomCode : 'SELECTION PENDING'}</span>
          </div>
        </div>

        <!-- VISA Validity Status Section (No Timer) -->
        <div class="visa-status-box ${isQualifiedForR2 ? 'qualified' : ''}">
          <div class="visa-status-header">
            <span class="visa-status-title">VISA STATUS / 滞在資格</span>
            ${isQualifiedForR2
              ? '<span class="visa-status-pill qualified">● EXTENDED / 延長</span>'
              : '<span class="visa-status-pill active">● VALID / 有効</span>'}
          </div>

          <div class="visa-status-main">
            ${isQualifiedForR2 ? `
              <div class="visa-validity-text qualified">
                VISA EXTENDED FOR ROUND 2
              </div>
              <div class="visa-validity-jp">第2ラウンド進出 — ビザ延長完了</div>
            ` : `
              <div class="visa-validity-text valid">
                VISA VALID FOR ROUND 1
              </div>
              <div class="visa-validity-jp">第1ラウンド有効 — ゲームに参加可能</div>
            `}
          </div>
        </div>

        <!-- Footer Authentication & Barcode -->
        <div class="visa-footer-section">
          <div class="visa-barcode-graphic"></div>
          <div class="visa-serial-code">VISA-AUTH // 8849-01-${teamCode}</div>
          <button class="visa-btn-dismiss" id="visa-modal-close" type="button">
            閉じる / CLOSE
          </button>
        </div>
      </div>
    `;

    const closeBtn = modal.querySelector('#visa-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
  } catch (err) {
    modal.innerHTML = `
      <div class="visa-card-container" style="text-align: center; padding: 24px;">
        <p class="status-note error">${err.message || 'Failed to load VISA information'}</p>
        <button class="visa-btn-dismiss" id="visa-modal-close" type="button" style="margin-top: 16px;">
          閉じる / CLOSE
        </button>
      </div>
    `;
    const closeBtn = modal.querySelector('#visa-modal-close');
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
  }
}

export function renderHome(root, navigate) {
  const roomId = localStorage.getItem('bl_room_id');

  root.innerHTML = `
    <div class="phone-dashboard-container">
      <!-- Main Phone Apps Screen -->
      <div class="phone-apps-view" id="phone-main-view">
        <div class="phone-apps-grid">
          <button class="phone-app-card-btn" id="app-btn-game" type="button">
            <div class="phone-app-card-icon">
              <img src="../shared/img/app_icon_game.png" alt="Game" />
            </div>
            <span class="phone-app-card-label">Game</span>
          </button>

          <button class="phone-app-card-btn" id="app-btn-visa" type="button">
            <div class="phone-app-card-icon">
              <img src="../shared/img/app_icon_visa.png" alt="VISA" />
            </div>
            <span class="phone-app-card-label">VISA</span>
          </button>
        </div>
      </div>

      <!-- Games Subview (Revealed when Game app is clicked) -->
      <div class="phone-games-subview" id="phone-games-subview" style="display: none;">
        <div class="games-subview-topbar">
          <button class="games-subview-back" id="games-subview-back" type="button">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg>
            <span>HOME</span>
          </button>
          <div class="games-subview-heading">
            <span class="jp">ゲーム選択</span>
            <span class="en">GAMES</span>
          </div>
        </div>

        <div class="games-subview-tiles" id="games-subview-tiles"></div>
      </div>
    </div>

    <nav class="diamond-nav">
      <button class="diamond-btn active" data-nav="home"><span class="diamond-icon">${NAV_ICONS.home}</span></button>
      <button class="diamond-btn" data-nav="camera"><span class="diamond-icon">${NAV_ICONS.camera}</span></button>
      <button class="diamond-btn" data-nav="leaderboard"><span class="diamond-icon">${NAV_ICONS.trophy}</span></button>
      <button class="diamond-btn" data-nav="account"><span class="diamond-icon">${NAV_ICONS.user}</span></button>
    </nav>
  `;

  const mainView = root.querySelector('#phone-main-view');
  const gamesSubview = root.querySelector('#phone-games-subview');
  const gamesGrid = root.querySelector('#games-subview-tiles');
  const backBtn = root.querySelector('#games-subview-back');
  const gameAppBtn = root.querySelector('#app-btn-game');
  const visaAppBtn = root.querySelector('#app-btn-visa');

  // Populate Games
  const gameTiles = [
    { route: '#/game/mindmaze', label: GAMES.MINDMAZE.en, jp: GAMES.MINDMAZE.jp, suit: 'CLUB' },
    { route: '#/game/ace-spade', label: GAMES.ACE_SPADE.en, jp: GAMES.ACE_SPADE.jp, suit: 'SPADE' },
    { route: '#/game/king-diamond', label: GAMES.KING_DIAMOND.en, jp: GAMES.KING_DIAMOND.jp, suit: 'DIAMOND' },
    { route: '#/game/jack-heart', label: GAMES.JACK_HEART.en, jp: GAMES.JACK_HEART.jp, suit: 'HEART' },
  ];

  gameTiles.forEach((g) => {
    const btn = document.createElement('button');
    btn.className = 'game-select-card';
    btn.innerHTML = `
      <div class="game-card-icon-wrap">
        ${suitIconSVG(g.suit, { size: 36 })}
      </div>
      <div class="game-card-text">
        <span class="game-card-jp">${g.jp || ''}</span>
        <span class="game-card-en">${g.label}</span>
      </div>
      <div class="game-card-arrow">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
      </div>
    `;
    btn.addEventListener('click', () => navigate(g.route));
    gamesGrid.appendChild(btn);
  });

  // Switch between Main Phone Apps and Games Subview
  function showMainView() {
    gamesSubview.style.display = 'none';
    mainView.style.display = 'flex';
  }

  function showGamesView() {
    mainView.style.display = 'none';
    gamesSubview.style.display = 'flex';
  }

  gameAppBtn.addEventListener('click', showGamesView);
  visaAppBtn.addEventListener('click', () => showVisaModal());
  backBtn.addEventListener('click', showMainView);

  root.querySelector('[data-nav="home"]').addEventListener('click', () => {
    showMainView();
  });

  root.querySelector('[data-nav="camera"]').addEventListener('click', () => showCameraLockedModal());
  root.querySelector('[data-nav="leaderboard"]').addEventListener('click', () => navigate('#/leaderboard'));
  root.querySelector('[data-nav="account"]').addEventListener('click', () => navigate('#/account'));

  // Live WebSocket Listener for Published Final Results & Qualifications
  if (roomId) {
    checkAndTriggerGlobalOutcome();
    new LiveChannel(`/rooms/${roomId}/leaderboard`, (data) => checkAndTriggerGlobalOutcome(data), 'team');

    api.team.roomSessions(roomId).then((sessions) => {
      sessions.forEach((s) => {
        if (s.is_published && s.session_id) {
          api.team.viewAck(s.session_id, 'PUBLISHED_RESULTS').catch(() => {});
        }
      });
    }).catch(() => {});
  }
}

export async function checkAndTriggerGlobalOutcome(lbData = null) {
  if (!getToken('team')) return;
  try {
    const roomId = localStorage.getItem('bl_room_id');
    const team = await api.team.me().catch(() => null);
    if (!team) return;

    let rows = Array.isArray(lbData) ? lbData : null;
    if (!rows && roomId) {
      rows = await api.team.roomLeaderboard(roomId).catch(() => []);
    }
    if (!rows || !rows.length) return;

    const myEntry = rows.find(r => r.team_code === team.team_code);
    // STRICT RULE: Only process final outcomes when all games are published and round is COMPLETED
    if (myEntry && myEntry.is_published === true && typeof myEntry.is_qualified === 'boolean') {
      // Acknowledge receipt of final published results to backend so admin panel confirms delivery
      api.team.ackPublishedResults().catch(() => {});

      if (myEntry.is_qualified === true) {
        // Qualified for Round 2: Remove any elimination overlay
        const laserOverlay = document.getElementById('laser-elimination-overlay');
        if (laserOverlay) laserOverlay.remove();

        // Automatically trigger VISA Extended animation for qualified teams
        const alreadyOpened = sessionStorage.getItem('bl_qualified_auto_opened');
        if (!alreadyOpened && !document.getElementById('visa-app-modal')) {
          sessionStorage.setItem('bl_qualified_auto_opened', '1');
          showVisaModal({ isQualifiedNotice: true, myEntry });
        }
      } else if (myEntry.is_qualified === false) {
        // Defensive guard: if EVERY team in the room shows is_qualified=false,
        // it's likely a transient state where room_results hasn't been
        // computed yet. Skip triggering the laser and wait for the next update.
        const publishedRows = rows.filter(r => r.is_published === true && typeof r.is_qualified === 'boolean');
        const anyQualified = publishedRows.some(r => r.is_qualified === true);
        if (!anyQualified && publishedRows.length > 1) {
          // All teams show not-qualified — likely a transient race. Wait.
          return;
        }

        // Eliminated: Trigger Sky Laser Strike
        const existingLaser = document.getElementById('laser-elimination-overlay');
        if (!existingLaser) {
          triggerLaserEliminationSequence();
        }
      }
    } else {
      // Games still in progress or not all published - reset flag and ensure no premature laser screen
      sessionStorage.removeItem('bl_qualified_auto_opened');
      const laserOverlay = document.getElementById('laser-elimination-overlay');
      if (laserOverlay) laserOverlay.remove();
    }
  } catch (_) {}
}


