import { getToken, clearToken, syncServerTime } from '../../shared/js/api.js?v=v36_publish_btn_fix';
import { renderLogin } from './screens/login.js?v=v36_publish_btn_fix';
import { renderDashboard } from './screens/dashboard.js?v=v36_publish_btn_fix';
import { renderRoomsScreen } from './screens/rooms.js?v=v36_publish_btn_fix';
import { renderRoomControl } from './screens/room-control.js?v=v36_publish_btn_fix';
import { renderTeamsAdmin } from './screens/teams-admin.js?v=v36_publish_btn_fix';
import { renderAdminAccounts } from './screens/admin-accounts.js?v=v36_publish_btn_fix';

const root = document.getElementById('app');

function decodeToken(token) {
  try {
    return JSON.parse(atob(token.split('.')[1]));
  } catch {
    return null;
  }
}

export function navigate(hash) {
  if (location.hash === hash) route(); else location.hash = hash;
}

function matchRoute(hash) {
  const path = hash.replace(/^#/, '') || '/login';
  const parts = path.split('/').filter(Boolean);

  if (parts[0] === 'login') return { screen: 'login' };
  if (parts[0] === 'dashboard') return { screen: 'dashboard' };
  if (parts[0] === 'rooms' && parts[1]) return { screen: 'room-control', roomId: parts[1], roundId: parts[2] };
  if (parts[0] === 'rooms') return { screen: 'rooms' };
  if (parts[0] === 'teams') return { screen: 'teams' };
  if (parts[0] === 'admins') return { screen: 'admins' };
  return { screen: 'dashboard' };
}

let currentCleanup = null;

function route() {
  if (typeof currentCleanup === 'function') {
    try { currentCleanup(); } catch (_) {}
  }
  currentCleanup = null;

  const token = getToken('admin');
  const match = matchRoute(location.hash);

  if (match.screen !== 'login' && !token) {
    location.hash = '#/login';
    return;
  }
  if (match.screen === 'login' && token) {
    location.hash = '#/dashboard';
    return;
  }

  if (match.screen === 'login') {
    root.className = 'admin-shell mode-light login-mode';
    root.innerHTML = `<div class="login-wrap" id="login-mount"></div>`;
    currentCleanup = renderLogin(root.querySelector('#login-mount'), navigate) ?? null;
    return;
  }

  const claims = decodeToken(token);
  if (!claims) {
    clearToken('admin');
    location.hash = '#/login';
    return;
  }
  const role = claims.role;
  if (!role) {
    clearToken('admin');
    location.hash = '#/login';
    return;
  }

  root.className = 'admin-shell mode-light';
  root.innerHTML = `
    <nav class="admin-nav" id="admin-nav">
      <div class="brand">V</div>
      <a href="#/dashboard" data-screen="dashboard"><span class="nav-icon"><span class="mi">dashboard</span></span> Dashboard</a>
      <a href="#/rooms" data-screen="rooms"><span class="nav-icon"><span class="mi">meeting_room</span></span> Rooms</a>
      <a href="#/teams" data-screen="teams"><span class="nav-icon"><span class="mi">group</span></span> Teams</a>
      <a href="#/admins" data-screen="admins" class="${role === 'SUPER_ADMIN' ? '' : 'disabled'}"><span class="nav-icon"><span class="mi">admin_panel_settings</span></span> Admin Accounts</a>
      <div class="role-tag">${role.replace('_', ' ')} · <a href="#" id="logout-link">Log out</a></div>
    </nav>
    <main class="admin-main" id="admin-main"></main>
  `;

  root.querySelectorAll('.admin-nav a[data-screen]').forEach((a) => {
    a.classList.toggle('active', a.dataset.screen === match.screen || (match.screen === 'room-control' && a.dataset.screen === 'rooms'));
  });
  root.querySelector('#logout-link').addEventListener('click', (e) => {
    e.preventDefault();
    clearToken('admin');
    navigate('#/login');
  });

  const main = root.querySelector('#admin-main');

  switch (match.screen) {
    case 'dashboard':    currentCleanup = renderDashboard(main, navigate, role) ?? null; break;
    case 'rooms':        currentCleanup = renderRoomsScreen(main, navigate, role) ?? null; break;
    case 'room-control': currentCleanup = renderRoomControl(main, navigate, match.roomId, match.roundId) ?? null; break;
    case 'teams':        currentCleanup = renderTeamsAdmin(main, navigate, role) ?? null; break;
    case 'admins':
      if (role !== 'SUPER_ADMIN') { main.innerHTML = `<p class="status-note">SUPER_ADMIN only.</p>`; break; }
      currentCleanup = renderAdminAccounts(main, navigate) ?? null;
      break;
  }
}

window.addEventListener('hashchange', route);

// Ensure accurate server time on load to sync admin time with game servers
syncServerTime().then(() => {
  if (document.readyState === 'loading') {
    window.addEventListener('DOMContentLoaded', route);
  } else {
    route();
  }
});
