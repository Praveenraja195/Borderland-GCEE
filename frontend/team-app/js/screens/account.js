import { api, clearToken } from '../../../shared/js/api.js';
import { HEADERS, BUTTONS, SUITS } from '../../../shared/js/copy.js';
import { suitIconSVG } from '../../../shared/js/suit-icons.js';
import { toast } from '../../../shared/js/ui.js';
import { showCameraLockedModal } from './home.js';
import { exitFullscreen } from '../fullscreen.js';

const NAV_ICONS = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>',
  trophy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0V4z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>',
  camera: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
};

export async function renderAccount(root, navigate) {
  root.innerHTML = `
    <div class="screen-header-bar">
      <button class="screen-back-btn" id="account-back-btn" type="button" aria-label="Back to Home">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
        <span>HOME</span>
      </button>
      <div class="bracket-header">
        <span class="jp">${HEADERS.account.jp}</span>
        <span class="en">${HEADERS.account.en}</span>
      </div>
      <div class="screen-header-placeholder"></div>
    </div>
    <div class="scroll-area" id="account-body" style="padding-bottom: 90px;">
      <div class="spinner-center" style="display:flex; justify-content:center; align-items:center; height:40vh;">
        <div class="spinner"></div>
      </div>
    </div>
    <nav class="diamond-nav">
      <button class="diamond-btn" data-nav="home"><span class="diamond-icon">${NAV_ICONS.home}</span></button>
      <button class="diamond-btn" data-nav="camera"><span class="diamond-icon">${NAV_ICONS.camera}</span></button>
      <button class="diamond-btn" data-nav="leaderboard"><span class="diamond-icon">${NAV_ICONS.trophy}</span></button>
      <button class="diamond-btn active" data-nav="account"><span class="diamond-icon">${NAV_ICONS.user}</span></button>
    </nav>
  `;

  // Attach back button and nav handlers
  const backBtn = root.querySelector('#account-back-btn');
  if (backBtn) backBtn.addEventListener('click', () => navigate('#/home'));

  root.querySelector('[data-nav="home"]').addEventListener('click', () => navigate('#/home'));
  root.querySelector('[data-nav="camera"]').addEventListener('click', () => showCameraLockedModal());
  root.querySelector('[data-nav="leaderboard"]').addEventListener('click', () => navigate('#/leaderboard'));
  root.querySelector('[data-nav="account"]').addEventListener('click', () => navigate('#/account'));

  const body = root.querySelector('#account-body');

  let team = null;
  let activeRound = null;
  let mySelection = null;

  try {
    team = await api.team.me();
  } catch (err) {
    body.innerHTML = `
      <div style="padding: 24px; text-align: center;">
        <p class="status-note error">${err.message || 'Failed to load account'}</p>
        <button id="logout-btn" class="cta-btn ghost" style="margin-top: 16px;">Log In Again</button>
      </div>
    `;
    const logoutBtn = body.querySelector('#logout-btn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => {
        clearToken('team');
        exitFullscreen();
        navigate('#/login');
      });
    }
    return;
  }

  try {
    activeRound = await api.team.getActiveRound().catch(() => null);
    if (activeRound && activeRound.round_id) {
      mySelection = await api.team.mySelection(activeRound.round_id).catch(() => null);
      if (mySelection && mySelection.suit_code) {
        localStorage.setItem('bl_team_suit', mySelection.suit_code.toUpperCase());
      }
    }
  } catch (_) {}

  // Determine suit and card info if selected
  const suitMeta = mySelection ? getSuitMeta(mySelection.suit_code || mySelection.suit_id) : null;
  const cardNumber = mySelection?.selected_number;
  const rank = formatRank(cardNumber);
  const roomCode = localStorage.getItem('bl_room_code') || (mySelection?.room_id ? 'Assigned' : 'Pending');

  body.innerHTML = `
    <div style="max-width: 480px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px;">
      
      <!-- Team Profile Card -->
      <div style="background: #ffffff; border: 1.5px solid var(--bl-border); border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); text-align: center;">
        <div style="width: 64px; height: 64px; background: #0f172a; color: #ffffff; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 12px; font-size: 1.6rem; font-weight: 900; box-shadow: 0 4px 12px rgba(15,23,42,0.2);">
          ${team.team_code.slice(0, 2).toUpperCase()}
        </div>
        <h2 style="font-size: 1.4rem; font-weight: 900; color: #0f172a; margin: 0 0 4px;">${team.team_name}</h2>
        <div style="display: inline-flex; align-items: center; gap: 6px; background: #f1f5f9; padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: 700; color: #475569; font-family: var(--font-mono); margin-top: 4px;">
          <span>ID:</span> <strong>${team.team_code}</strong>
        </div>
      </div>

      <!-- Assigned Card & Room Details -->
      <div style="background: #ffffff; border: 1.5px solid var(--bl-border); border-radius: 12px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04);">
        <div style="font-size: 0.78rem; font-weight: 800; color: #64748b; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 12px;">
          Card & Room Assignment / 割り当て情報
        </div>
        
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
          <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">Assigned Card</div>
            ${suitMeta && cardNumber ? `
              <div style="font-size: 1.35rem; font-weight: 900; color: ${suitMeta.isRed ? '#dc2626' : '#0f172a'}; display: flex; align-items: center; justify-content: center; gap: 6px;">
                <span>${suitMeta.icon}</span> <span>${rank.short}</span>
              </div>
              <div style="font-size: 0.72rem; color: #64748b; margin-top: 2px; font-weight: 600;">${suitMeta.name} ${rank.long}</div>
            ` : `
              <div style="font-size: 0.88rem; font-weight: 700; color: #94a3b8;">Not Selected</div>
            `}
          </div>

          <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px; text-align: center;">
            <div style="font-size: 0.72rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">Assigned Room</div>
            <div style="font-size: 1.15rem; font-weight: 900; color: var(--bl-ink);">
              ${roomCode || 'Room 1'}
            </div>
            <div style="font-size: 0.7rem; color: #166534; font-weight: 600; margin-top: 2px;">● Connected</div>
          </div>
        </div>
      </div>

      <!-- Account Status -->
      <div style="background: #ffffff; border: 1.5px solid var(--bl-border); border-radius: 12px; padding: 16px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div style="font-size: 0.85rem; font-weight: 700; color: #0f172a;">Session Status</div>
          <div style="font-size: 0.75rem; color: #64748b;">Authenticated as Active Player</div>
        </div>
        <span style="background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; font-size: 0.78rem; font-weight: 700; padding: 4px 10px; border-radius: 12px; display: inline-flex; align-items: center; gap: 4px;">
          <span style="display:inline-block; width:6px; height:6px; background:#10b981; border-radius:50%;"></span>
          Active
        </span>
      </div>

      <!-- Actions -->
      <div style="margin-top: 8px;">
        <button id="logout-btn" class="cta-btn ghost" style="color: var(--bl-red); border-color: rgba(229,57,53,0.3);" type="button">
          ログアウト / Log Out
        </button>
      </div>

    </div>
  `;

  body.querySelector('#logout-btn').addEventListener('click', () => {
    if (confirm('ログアウトしますか？ / Are you sure you want to log out?')) {
      clearToken('team');
      exitFullscreen();
      localStorage.removeItem('bl_room_id');
      localStorage.removeItem('bl_room_code');
      toast('Logged out');
      navigate('#/login');
    }
  });
}

const RANK_NAMES = {
  1: { short: 'A', long: 'Ace' },
  11: { short: 'J', long: 'Jack' },
  12: { short: 'Q', long: 'Queen' },
  13: { short: 'K', long: 'King' },
};

function formatRank(num) {
  if (!num) return { short: '', long: '' };
  return RANK_NAMES[num] || { short: String(num), long: String(num) };
}

function getSuitMeta(suit) {
  if (!suit) return null;
  // If string suit code (e.g. 'HEART', 'SPADE', 'CLUB', 'DIAMOND')
  if (typeof suit === 'string' && isNaN(Number(suit))) {
    const code = suit.toUpperCase();
    if (code === 'HEART') return { code: 'HEART', name: 'Heart', icon: '♥', isRed: true };
    if (code === 'SPADE') return { code: 'SPADE', name: 'Spade', icon: '♠', isRed: false };
    if (code === 'CLUB') return { code: 'CLUB', name: 'Club', icon: '♣', isRed: false };
    if (code === 'DIAMOND') return { code: 'DIAMOND', name: 'Diamond', icon: '♦', isRed: true };
  }
  // By PostgreSQL database ID in 'suits' table (1: HEART, 2: SPADE, 3: CLUB, 4: DIAMOND)
  switch (Number(suit)) {
    case 1:
      return { code: 'HEART', name: 'Heart', icon: '♥', isRed: true };
    case 2:
      return { code: 'SPADE', name: 'Spade', icon: '♠', isRed: false };
    case 3:
      return { code: 'CLUB', name: 'Club', icon: '♣', isRed: false };
    case 4:
      return { code: 'DIAMOND', name: 'Diamond', icon: '♦', isRed: true };
    default:
      return { code: 'UNKNOWN', name: 'Card', icon: '🂠', isRed: false };
  }
}
