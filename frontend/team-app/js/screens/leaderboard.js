import { api, getToken } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { LiveChannel } from '../../../shared/js/ws.js';
import { showCameraLockedModal } from './home.js';

const NAV_ICONS = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>',
  trophy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
};

function decodeTeamCode(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.team_code || null;
  } catch {
    return null;
  }
}

function formatScore(val) {
  if (val === null || val === undefined || isNaN(Number(val))) return '—';
  return Number(val).toFixed(1);
}

function formatRank(n) {
  if (!n && n !== 0) return '—';
  const num = Number(n);
  if (isNaN(num)) return '—';
  return `${num}`;
}

export function renderLeaderboard(root, navigate) {
  let roomId = localStorage.getItem('bl_room_id');
  let myTeamCode = localStorage.getItem('bl_team_code') || decodeTeamCode(getToken('team') || '');

  root.classList.add('has-leaderboard');

  root.innerHTML = `
    <div class="screen-header-bar">
      <button class="screen-back-btn" id="lb-back-btn" type="button" aria-label="Back to Home">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
        <span>HOME</span>
      </button>
      <div class="bracket-header">
        <span class="jp">${HEADERS.leaderboard.jp}</span>
        <span class="en">${HEADERS.leaderboard.en}</span>
      </div>
      <div class="screen-header-placeholder"></div>
    </div>

    <div class="bl-lb-wrapper">
      <div class="bl-lb-scroll-area" id="lb-scroll-area">
        <div id="lb-area">
          <div class="spinner" style="margin: 40px auto;"></div>
        </div>
      </div>

      <!-- Floating Quick-Access Dock (appears when user's team row is scrolled out of view) -->
      <div class="bl-lb-floating-dock" id="bl-lb-floating-dock">
        <div class="bl-dock-info">
          <span class="bl-dock-badge">▶ YOUR TEAM / 参加チーム</span>
          <div class="bl-dock-details">
            <span class="bl-dock-rank" id="bl-dock-rank">#—</span>
            <span class="bl-dock-name" id="bl-dock-name">—</span>
            <span class="bl-dock-pts" id="bl-dock-pts">— PTS</span>
          </div>
        </div>
        <button class="bl-dock-locate-btn" id="bl-dock-locate-btn" type="button" aria-label="Locate your team in standings">
          LOCATE ⌖
        </button>
      </div>

      <!-- Floating Scroll-to-Top Button -->
      <button class="bl-lb-scroll-top-btn" id="bl-lb-scroll-top-btn" type="button" aria-label="Scroll to top of standings">
        ▲ TOP
      </button>
    </div>

    <nav class="diamond-nav">
      <button class="diamond-btn" data-nav="home"><span class="diamond-icon">${NAV_ICONS.home}</span></button>
      <button class="diamond-btn" data-nav="camera"><span class="diamond-icon">${NAV_ICONS.camera}</span></button>
      <button class="diamond-btn active" data-nav="leaderboard"><span class="diamond-icon">${NAV_ICONS.trophy}</span></button>
      <button class="diamond-btn" data-nav="account"><span class="diamond-icon">${NAV_ICONS.user}</span></button>
    </nav>
  `;

  // Attach back button and nav handlers
  const backBtn = root.querySelector('#lb-back-btn');
  if (backBtn) backBtn.addEventListener('click', () => navigate('#/home'));

  root.querySelector('[data-nav="home"]').addEventListener('click', () => navigate('#/home'));
  root.querySelector('[data-nav="camera"]').addEventListener('click', () => showCameraLockedModal());
  root.querySelector('[data-nav="leaderboard"]').addEventListener('click', () => navigate('#/leaderboard'));
  root.querySelector('[data-nav="account"]').addEventListener('click', () => navigate('#/account'));

  const area = root.querySelector('#lb-area');
  const scrollArea = root.querySelector('#lb-scroll-area');
  const floatingDock = root.querySelector('#bl-lb-floating-dock');
  const scrollTopBtn = root.querySelector('#bl-lb-scroll-top-btn');
  const dockRankEl = root.querySelector('#bl-dock-rank');
  const dockNameEl = root.querySelector('#bl-dock-name');
  const dockPtsEl = root.querySelector('#bl-dock-pts');
  const dockLocateBtn = root.querySelector('#bl-dock-locate-btn');

  let currentMyEntry = null;

  function locateMyTeam() {
    if (!area) return;
    const meRow = area.querySelector('.bl-lb-row.me');
    if (meRow) {
      meRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
      meRow.classList.add('locate-highlight');
      setTimeout(() => meRow.classList.remove('locate-highlight'), 1800);
      if (floatingDock) floatingDock.classList.remove('visible');
    }
  }

  if (dockLocateBtn) {
    dockLocateBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      locateMyTeam();
    });
  }
  if (floatingDock) {
    floatingDock.addEventListener('click', locateMyTeam);
  }
  if (scrollTopBtn && scrollArea) {
    scrollTopBtn.addEventListener('click', () => {
      scrollArea.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  let scrollTicking = false;
  function onScroll() {
    if (!scrollTicking) {
      requestAnimationFrame(() => {
        updateScrollHelpers();
        scrollTicking = false;
      });
      scrollTicking = true;
    }
  }

  function updateScrollHelpers() {
    if (!scrollArea) return;
    const st = scrollArea.scrollTop;

    if (scrollTopBtn) {
      if (st > 220) {
        scrollTopBtn.classList.add('visible');
      } else {
        scrollTopBtn.classList.remove('visible');
      }
    }

    if (floatingDock) {
      if (currentMyEntry) {
        const meRow = area.querySelector('.bl-lb-row.me');
        if (meRow) {
          const scrollRect = scrollArea.getBoundingClientRect();
          const meRect = meRow.getBoundingClientRect();
          const isVisible = (meRect.top >= scrollRect.top + 30 && meRect.bottom <= scrollRect.bottom - 20);
          if (!isVisible && st > 60) {
            floatingDock.classList.add('visible');
          } else {
            floatingDock.classList.remove('visible');
          }
        } else {
          floatingDock.classList.remove('visible');
        }
      } else {
        floatingDock.classList.remove('visible');
      }
    }
  }

  if (scrollArea) {
    scrollArea.addEventListener('scroll', onScroll, { passive: true });
  }

  let channel = null;
  let currentTab = 'overall';
  let lastRows = null;
  let lastKind = 'overall';

  // Stores previous snapshot per team_code: { rank, mm, kd, jh, total }
  const previousState = new Map();
  let isFirstRender = true;

  // Asynchronously resolve myTeamCode from /teams/me if missing
  if (!myTeamCode && getToken('team')) {
    api.team.me().then((me) => {
      if (me && me.team_code) {
        myTeamCode = me.team_code;
        localStorage.setItem('bl_team_code', myTeamCode);
        if (lastRows && lastRows.length > 0) {
          renderRows(lastRows, lastKind);
        }
      }
    }).catch(() => {});
  }

  // ── Render Leaderboard Rows with FLIP Position Animations ───────────────
  function renderRows(rows, kind) {
    lastRows = rows;
    lastKind = kind;

    if (!rows || rows.length === 0) {
      area.innerHTML = `
        <div class="bl-standby-hero">
          <div class="bl-standby-badge">● Standby</div>
          <h3 class="bl-standby-title">順位データなし / No Results</h3>
          <p class="bl-standby-sub">ラウンドが終了すると順位が表示されます。</p>
        </div>
      `;
      previousState.clear();
      isFirstRender = true;
      return;
    }

    const hasPublishedResults = rows.some(
      (r) => r.is_published || r.total_score !== null || r.mindmaze_score !== null || r.ace_spade_score !== null || r.king_diamond_score !== null || r.jack_heart_score !== null
    );

    if (!hasPublishedResults) {
      area.innerHTML = `
        <div class="bl-standby-hero">
          <div class="bl-standby-badge">● Results Pending</div>
          <h3 class="bl-standby-title">結果発表をお待ちください</h3>
          <p class="bl-standby-sub">
            管理者が結果を公開すると、全チームの順位表が表示されます。<br>
            <span style="font-size:0.75rem;">Standings will be revealed once published by Admin.</span>
          </p>
          <div class="spinner" style="margin: 16px auto; width: 32px; height: 32px;"></div>
        </div>
      `;
      previousState.clear();
      isFirstRender = true;
      return;
    }

    // Acknowledge published results for active sessions
    if (roomId) {
      api.team.roomSessions(roomId).then((sessions) => {
        sessions.forEach((s) => {
          if (s.is_published && s.session_id) {
            api.team.viewAck(s.session_id, 'PUBLISHED_RESULTS').catch(() => {});
          }
        });
      }).catch(() => {});
    }

    const rankKey = kind === 'room' ? 'live_rank' : 'overall_rank';

    // Sort rows by rank / total score
    const sortedRows = [...rows].sort((a, b) => {
      const rA = a[rankKey] ?? 9999;
      const rB = b[rankKey] ?? 9999;
      if (rA !== rB) return rA - rB;
      return (Number(b.total_score) || 0) - (Number(a.total_score) || 0);
    });

    // Detect user's team entry for the status card
    let myEntry = null;
    let myRank = null;
    let mySuit = null;
    if (myTeamCode) {
      const foundIdx = sortedRows.findIndex(
        (r) => r.team_code && r.team_code.toUpperCase() === myTeamCode.toUpperCase()
      );
      if (foundIdx !== -1) {
        myEntry = sortedRows[foundIdx];
        myRank = myEntry[rankKey] ?? (foundIdx + 1);
        mySuit = getTeamSuit(myEntry, true);
      }
    }

    currentMyEntry = myEntry;
    if (myEntry) {
      if (dockRankEl) dockRankEl.textContent = `#${myRank}`;
      if (dockNameEl) dockNameEl.textContent = myEntry.team_name || myEntry.team_code;
      if (dockPtsEl) dockPtsEl.textContent = `${formatScore(myEntry.total_score)} PTS`;
    }

    let myStatusCardHtml = '';
    if (myEntry) {
      myStatusCardHtml = `
        <div class="bl-my-status-card" id="bl-my-status-card">
          <div class="bl-my-status-left">
            <div class="bl-my-status-badge">▶ YOUR TEAM / 参加チーム</div>
            <div class="bl-my-status-name">${myEntry.team_name || myEntry.team_code}</div>
            <div class="bl-my-status-metrics">
              <span class="bl-my-stat-pill">RANK <strong class="val">#${myRank}</strong></span>
              <span class="bl-my-stat-pill">PTS <strong class="val">${formatScore(myEntry.total_score)}</strong></span>
              <span class="bl-my-stat-pill suit-color-${mySuit.toLowerCase()}">${SUIT_SYMBOLS[mySuit] || ''}</span>
            </div>
          </div>
          <button class="bl-my-locate-btn" id="bl-locate-me-btn" type="button" aria-label="Locate your team in leaderboard">
            LOCATE ⌖
          </button>
        </div>
      `;
    }

    let rowList = area.querySelector('#bl-lb-list');

    // ── INITIAL FULL MOUNT ────────────────────────────────────────────────
    if (!rowList || isFirstRender) {
      area.innerHTML = `
        <div class="bl-lb-hud-header">
          <div class="bl-hud-top-bar">
            <div class="bl-hud-beacon">
              <span class="bl-beacon-dot"></span>
              <span class="bl-beacon-tag">LIVE FEED // 生存順位</span>
            </div>
            <div class="bl-hud-total-tag">
              <span class="bl-hud-count-val">${sortedRows.length}</span> TEAMS IN BORDERLAND
            </div>
          </div>
          <div class="bl-hud-title-row">
            <div class="bl-hud-main-title">SURVIVAL LEADERBOARD</div>
            <div class="bl-hud-sub-title">今際の国 // 全体順位表</div>
          </div>
        </div>

        ${myStatusCardHtml}

        <div class="bl-lb-col-headers">
          <div class="bl-th-rank">RANK</div>
          <div class="bl-th-team">SURVIVOR TEAM</div>
          <div class="bl-th-pts">POINTS</div>
          <div class="bl-th-suit">SUIT</div>
        </div>
        <div class="bl-lb-list" id="bl-lb-list"></div>
      `;
      rowList = area.querySelector('#bl-lb-list');

      // Hook locate button on status card
      const locateBtn = area.querySelector('#bl-locate-me-btn');
      if (locateBtn) {
        locateBtn.addEventListener('click', locateMyTeam);
      }

      sortedRows.forEach((r, idx) => {
        const rank = r[rankKey] ?? (idx + 1);
        const rowEl = createRowElement(r, rank, false, false, false, false, false);
        rowList.appendChild(rowEl);

        previousState.set(r.team_code, {
          rank,
          total: r.total_score,
          mm: r.mindmaze_score,
          as: r.ace_spade_score,
          kd: r.king_diamond_score,
          jh: r.jack_heart_score,
        });
      });

      // End of standings indicator
      const endMarker = document.createElement('div');
      endMarker.className = 'bl-lb-end-marker';
      endMarker.innerHTML = `
        <span class="bl-end-line"></span>
        <span class="bl-end-text">// END OF STANDINGS // 全${sortedRows.length}チーム //</span>
        <span class="bl-end-line"></span>
      `;
      rowList.appendChild(endMarker);

      isFirstRender = false;
      updateScrollHelpers();
      return;
    }

    // Update the My Status Card if present
    const existingCard = area.querySelector('#bl-my-status-card');
    if (myEntry) {
      if (existingCard) {
        const rankValEl = existingCard.querySelector('.bl-my-stat-pill .val');
        if (rankValEl) rankValEl.textContent = `#${myRank}`;
        const ptsValEl = existingCard.querySelectorAll('.bl-my-stat-pill .val')[1];
        if (ptsValEl) ptsValEl.textContent = formatScore(myEntry.total_score);
      } else {
        const headers = area.querySelector('.bl-lb-col-headers');
        if (headers) {
          headers.insertAdjacentHTML('beforebegin', myStatusCardHtml);
          const newLocateBtn = area.querySelector('#bl-locate-me-btn');
          if (newLocateBtn) {
            newLocateBtn.addEventListener('click', locateMyTeam);
          }
        }
      }
    } else if (existingCard) {
      existingCard.remove();
    }

    // ── FLIP ANIMATION ENGINE (First, Last, Invert, Play) ─────────────────
    // 1. FIRST: Capture current DOM positions
    const oldPositions = new Map();
    rowList.querySelectorAll('.bl-lb-row').forEach((el) => {
      const code = el.dataset.teamCode;
      if (code) {
        oldPositions.set(code, el.getBoundingClientRect().top);
      }
    });

    // 2. Track score changes
    const scoreChanges = new Map();
    sortedRows.forEach((r) => {
      const prev = previousState.get(r.team_code);
      const totalChanged = prev && prev.total !== r.total_score;
      const mmChanged = prev && prev.mm !== r.mindmaze_score;
      const asChanged = prev && prev.as !== r.ace_spade_score;
      const kdChanged = prev && prev.kd !== r.king_diamond_score;
      const jhChanged = prev && prev.jh !== r.jack_heart_score;
      scoreChanges.set(r.team_code, { totalChanged, mmChanged, asChanged, kdChanged, jhChanged });
    });

    // 3. Update DOM rows & reorder
    sortedRows.forEach((r, idx) => {
      const rank = r[rankKey] ?? (idx + 1);
      const chg = scoreChanges.get(r.team_code) || {};

      let rowEl = rowList.querySelector(`.bl-lb-row[data-team-code="${r.team_code}"]`);
      if (!rowEl) {
        rowEl = createRowElement(r, rank, chg.totalChanged, chg.mmChanged, chg.asChanged, chg.kdChanged, chg.jhChanged);
      } else {
        updateRowElement(rowEl, r, rank, chg.totalChanged, chg.mmChanged, chg.asChanged, chg.kdChanged, chg.jhChanged);
      }

      rowList.appendChild(rowEl);
    });

    // Ensure end marker is at the bottom of rowList
    let endMarker = rowList.querySelector('.bl-lb-end-marker');
    if (!endMarker) {
      endMarker = document.createElement('div');
      endMarker.className = 'bl-lb-end-marker';
    }
    endMarker.innerHTML = `
      <span class="bl-end-line"></span>
      <span class="bl-end-text">// END OF STANDINGS // 全${sortedRows.length}チーム //</span>
      <span class="bl-end-line"></span>
    `;
    rowList.appendChild(endMarker);
    updateScrollHelpers();

    // 4. LAST: Capture new DOM positions
    const newPositions = new Map();
    rowList.querySelectorAll('.bl-lb-row').forEach((el) => {
      const code = el.dataset.teamCode;
      if (code) {
        newPositions.set(code, el.getBoundingClientRect().top);
      }
    });

    // 5. INVERT & PLAY: Smoothly glide rows up and down
    rowList.querySelectorAll('.bl-lb-row').forEach((el) => {
      const code = el.dataset.teamCode;
      const oldTop = oldPositions.get(code);
      const newTop = newPositions.get(code);

      if (oldTop !== undefined && newTop !== undefined) {
        const deltaY = oldTop - newTop;
        if (deltaY !== 0) {
          el.style.transform = `translateY(${deltaY}px)`;
          el.style.transition = 'none';

          requestAnimationFrame(() => {
            el.style.transition = 'transform 600ms cubic-bezier(0.2, 0.9, 0.3, 1), background 0.3s ease, border-color 0.3s ease';
            el.style.transform = 'translateY(0)';
          });
        }
      }
    });

    // 6. Save current snapshot
    sortedRows.forEach((r, idx) => {
      const rank = r[rankKey] ?? (idx + 1);
      previousState.set(r.team_code, {
        rank,
        total: r.total_score,
        mm: r.mindmaze_score,
        as: r.ace_spade_score,
        kd: r.king_diamond_score,
        jh: r.jack_heart_score,
      });
    });

    // Clear flash styles after animation completes
    setTimeout(() => {
      if (rowList) {
        rowList.querySelectorAll('.score-flash').forEach((el) => {
          el.classList.remove('score-flash');
        });
      }
    }, 1000);
  }

  // ── Helper: Suit Symbols & Character Resolver ───────────────────────────
  const SUIT_SYMBOLS = {
    SPADE: '♠',
    HEART: '♥',
    DIAMOND: '♦',
    CLUB: '♣',
  };

  // Reverse map: symbol character → code
  const SYMBOL_TO_CODE = { '♠': 'SPADE', '♥': 'HEART', '♦': 'DIAMOND', '♣': 'CLUB' };

  function getTeamSuit(r, isMe) {
    let code = (r.team_suit_code || r.suit_code || r.suit || '').toUpperCase();
    // If code is empty or invalid, try to reverse-map from the symbol character
    if ((!code || !SUIT_SYMBOLS[code]) && r.team_suit_symbol) {
      code = SYMBOL_TO_CODE[r.team_suit_symbol] || '';
    }
    if (!code && isMe) {
      code = (localStorage.getItem('bl_team_suit') || localStorage.getItem('bl_suit') || '').toUpperCase();
    }
    if (!code || !SUIT_SYMBOLS[code]) {
      const fallbackSuits = ['SPADE', 'HEART', 'DIAMOND', 'CLUB'];
      const seed = r.team_code ? r.team_code.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0) : 0;
      code = fallbackSuits[seed % 4];
    }
    return code;
  }

  // ── Helper: Create a single team row element ───────────────────────────
  function createRowElement(r, rank, totalChg, mmChg, asChg, kdChg, jhChg) {
    const isMe = Boolean(
      (myTeamCode && r.team_code && r.team_code.toUpperCase() === myTeamCode.toUpperCase()) ||
      r.is_me ||
      r.is_current_team
    );
    const suitCode = getTeamSuit(r, isMe);
    const rankClass = rank === 1 ? 'rank-1' : rank <= 3 ? 'rank-top3' : '';
    const el = document.createElement('div');
    el.className = `bl-lb-row suit-${suitCode.toLowerCase()} ${rankClass} ${isMe ? 'me' : ''}`;
    el.dataset.teamCode = r.team_code;
    updateRowElement(el, r, rank, totalChg, mmChg, asChg, kdChg, jhChg);
    return el;
  }

  // ── Helper: Update an existing team row element ────────────────────────
  function updateRowElement(el, r, rank, totalChg, mmChg, asChg, kdChg, jhChg) {
    const isMe = Boolean(
      (myTeamCode && r.team_code && r.team_code.toUpperCase() === myTeamCode.toUpperCase()) ||
      r.is_me ||
      r.is_current_team
    );
    const suitCode = getTeamSuit(r, isMe);
    const suitSymbol = SUIT_SYMBOLS[suitCode] || '♠';

    const rankClass = rank === 1 ? 'rank-1' : rank <= 3 ? 'rank-top3' : '';
    el.className = `bl-lb-row suit-${suitCode.toLowerCase()} ${rankClass} ${isMe ? 'me' : ''}`;

    const youBadge = isMe ? '<span class="bl-you-badge">[ YOU ]</span>' : '';
    const totalVal = formatScore(r.total_score);
    const displayName = r.team_name || r.team_code;
    const rankDisplay = formatRank(rank).padStart(2, '0');

    el.innerHTML = `
      <div class="bl-col-rank">
        <span class="bl-rank-tag">${rankDisplay}</span>
      </div>

      <div class="bl-col-team">
        <div class="bl-team-label-wrap">
          <span class="bl-team-name">${displayName}</span>
          ${youBadge}
        </div>
      </div>

      <div class="bl-col-pts">
        <span class="bl-pts-num ${totalChg ? 'score-flash' : ''}">${totalVal}</span>
        <span class="bl-pts-unit">PTS</span>
      </div>

      <div class="bl-col-suit suit-color-${suitCode.toLowerCase()}">
        <span class="bl-suit-symbol">${suitSymbol}</span>
      </div>
    `;
  }

  // ── Room ID Resolution ──────────────────────────────────────────────────
  async function resolveRoomId() {
    if (roomId) return roomId;
    try {
      const st = await api.team.status();
      if (st?.selection?.room_id) {
        roomId = st.selection.room_id;
        localStorage.setItem('bl_room_id', roomId);
        return roomId;
      }
      if (st?.round?.round_id) {
        const sel = await api.team.mySelection(st.round.round_id);
        if (sel?.room_id) {
          roomId = sel.room_id;
          localStorage.setItem('bl_room_id', roomId);
          return roomId;
        }
      }
    } catch (_) {}
    return null;
  }

  // ── Tab Loading & LiveChannel Lifecycle ──────────────────────────────────
  async function loadTab(tab) {
    currentTab = tab;
    isFirstRender = true;
    previousState.clear();

    area.innerHTML = `<div class="spinner" style="margin: 40px auto;"></div>`;

    if (channel) {
      channel.close();
      channel = null;
    }

    try {
      if (tab === 'room') {
        const resolvedRoomId = await resolveRoomId();
        if (!resolvedRoomId) {
          const overallRows = await api.team.overallLeaderboard();
          if (overallRows && overallRows.length > 0) {
            renderRows(overallRows, 'overall');
            return;
          }
          area.innerHTML = `
            <div class="bl-standby-hero">
              <div class="bl-standby-badge">● Standby</div>
              <h3 class="bl-standby-title">ルーム未参加 / Join a Room</h3>
              <p class="bl-standby-sub">カード選択を完了してルームに参加してください。</p>
            </div>
          `;
          return;
        }

        const rows = await api.team.roomLeaderboard(resolvedRoomId);
        renderRows(rows, 'room');

        channel = new LiveChannel(`/rooms/${resolvedRoomId}/leaderboard`, (data) => {
          renderRows(data, 'room');
        });
      } else {
        const rows = await api.team.overallLeaderboard();
        renderRows(rows, 'overall');

        channel = new LiveChannel('/leaderboard/overall', (data) => {
          renderRows(data, 'overall');
        });
      }
    } catch (err) {
      area.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  // Initial load - always show overall leaderboard
  loadTab('overall');

  // Cleanup on screen dispose
  return () => {
    root.classList.remove('has-leaderboard');
    if (scrollArea) scrollArea.removeEventListener('scroll', onScroll);
    if (channel) channel.close();
  };
}


