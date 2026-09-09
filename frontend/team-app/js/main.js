import { api, getToken, syncServerTime } from '../../shared/js/api.js?v=v54_final_results_gate';
import { renderLogin } from './screens/login.js?v=v54_final_results_gate';
import { renderSelection } from './screens/selection.js?v=v54_final_results_gate';
import { renderWaiting } from './screens/waiting.js?v=v54_final_results_gate';
import { renderHome, checkAndTriggerGlobalOutcome } from './screens/home.js?v=v54_final_results_gate';
import { renderMindmaze } from './screens/games/mindmaze.js?v=v54_final_results_gate';
import { renderAceSpade } from './screens/games/ace-spade.js?v=v54_final_results_gate';
import { renderKingDiamond } from './screens/games/king-diamond.js?v=v54_final_results_gate';
import { renderJackHeart } from './screens/games/jack-heart.js?v=v54_final_results_gate';
import { renderLeaderboard } from './screens/leaderboard.js?v=v54_final_results_gate';
import { renderAccount } from './screens/account.js?v=v54_final_results_gate';

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

// Global View-Ack & Qualification Synchronizer
async function syncGlobalState() {
  if (!getToken('team')) return;
  try {
    await api.team.ackPublishedResults().catch(() => {});
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