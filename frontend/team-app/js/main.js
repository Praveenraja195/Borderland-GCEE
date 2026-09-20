import { api, getToken, syncServerTime } from '../../shared/js/api.js?v=v64_login_hints';
import { renderLogin } from './screens/login.js?v=v64_login_hints';
import { renderSelection } from './screens/selection.js?v=v64_login_hints';
import { renderWaiting } from './screens/waiting.js?v=v64_login_hints';
import { renderHome, checkAndTriggerGlobalOutcome } from './screens/home.js?v=v64_login_hints';
import { renderMindmaze } from './screens/games/mindmaze.js?v=v64_login_hints';
import { renderAceSpade } from './screens/games/ace-spade.js?v=v64_login_hints';
import { renderKingDiamond } from './screens/games/king-diamond.js?v=v64_login_hints';
import { renderJackHeart } from './screens/games/jack-heart.js?v=v64_login_hints';
import { renderLeaderboard } from './screens/leaderboard.js?v=v64_login_hints';
import { renderAccount } from './screens/account.js?v=v64_login_hints';
import { keepFullscreen } from './fullscreen.js?v=v64_login_hints';

const root = document.getElementById('app');

// route table: hash -> { render(root, navigate), mode: 'light'|'dark', auth: bool }
const ROUTES = {
  '#/login': { render: renderLogin, mode: 'light', auth: false },
  '#/selection': { render: renderSelection, mode: 'light', auth: true },
  '#/waiting': { render: renderWaiting, mode: 'light', auth: true },
  '#/home': { render: renderHome, mode: 'dark', auth: true },
  '#/game/mindmaze': { render: renderMindmaze, mode: 'light', auth: true },
  '#/game/ace-spade': { render: renderAceSpade, mode: 'light', auth: true },
  '#/game/king-diamond': { render: renderKingDiamond, mode: 'light', auth: true },
  '#/game/jack-heart': { render: renderJackHeart, mode: 'light', auth: true },
  '#/leaderboard': { render: renderLeaderboard, mode: 'dark', auth: true },
  '#/account': { render: renderAccount, mode: 'light', auth: true },
  '#/settings': { render: renderAccount, mode: 'light', auth: true },
};

export function navigate(hash) {
  if (location.hash === hash) { route(); } else { location.hash = hash; }
}

// Presence heartbeat + published-results check. The results ack itself is
// sent from checkAndTriggerGlobalOutcome once the outcome is on screen, so an
// ack on the admin board always means "seen", never just "polling".
async function syncGlobalState() {
  if (!getToken('team')) return;
  try {
    await api.team.heartbeat().catch(() => {});
    await checkAndTriggerGlobalOutcome();
  } catch (_) { }
}

let currentCleanup = null;

function route() {
  if (typeof currentCleanup === 'function') {
    try { currentCleanup(); } catch (_) { }
  }
  currentCleanup = null;

  let hash = location.hash || '#/login';
  let entry = ROUTES[hash.split('?')[0]];
  if (!entry) { hash = '#/login'; entry = ROUTES[hash]; }

  if (entry.auth && !getToken('team')) {
    location.hash = '#/login';
    return;
  }

  root.className = `app-shell mode-${entry.mode}`;
  root.innerHTML = '';
  currentCleanup = entry.render(root, navigate) ?? null;

  syncGlobalState();
}

window.addEventListener('hashchange', route);

// Once a team is logged in, any tap while out of full screen puts it back
// (login itself enters it from the login tap).
keepFullscreen();

// Poll for published results and final qualification status every 3 seconds while active
setInterval(syncGlobalState, 3000);

// Ensure accurate server time on load/reload to handle clock skew during active games
syncServerTime().then(() => {
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', route);
  } else {
    route();
  }
});