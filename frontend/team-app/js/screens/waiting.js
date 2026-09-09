import { api } from '../../../shared/js/api.js';
import { HEADERS, STATUS } from '../../../shared/js/copy.js';
import { getActiveRoundId } from './settings.js';

export function renderWaiting(root, navigate) {
  const roundId = getActiveRoundId();
  root.innerHTML = `
    <div class="bracket-header"><span class="jp">${HEADERS.round.jp}</span><span class="en">${HEADERS.round.en}</span></div>
    <div class="countdown-wrap">
      <div class="spinner"></div>
      <div class="countdown-label">${STATUS.waitingToStart.jp} / ${STATUS.waitingToStart.en}</div>
      <p class="status-note" id="detail"></p>
    </div>
  `;

  let stopped = false;
  const detail = root.querySelector('#detail');

  async function poll() {
    if (stopped) return;
    try {
      const sel = await api.team.mySelection(roundId);
      detail.textContent = sel.room_id
        ? `Assigned — room confirmed.`
        : `Selection locked — waiting for room assignment…`;
      if (sel.room_id) {
        localStorage.setItem('bl_room_id', sel.room_id);
        if (sel.suit_code) {
          localStorage.setItem('bl_team_suit', sel.suit_code.toUpperCase());
        }
        navigate('#/home');
        return;
      }
    } catch (err) {
      if (err.status === 404) {
        navigate('#/selection');
        return;
      }
      detail.textContent = err.message;
    }
    setTimeout(poll, 3000);
  }
  poll();

  return () => { stopped = true; };
}
