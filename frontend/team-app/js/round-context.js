// Workaround for API reference §6.4: no team-facing endpoint currently
// returns the live per-game round_id or its deadline. Until the backend
// ships one of the two fixes it proposes, the frontend caches whatever an
// admin relays (QR code / room screen) per game+session, keyed by session_id
// so a new session (after a restart) doesn't reuse a stale cached round.

const KEY = 'bl_round_ctx'; // { [sessionId]: { roundId, deadline, roundNumber } }

function readAll() {
  try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; }
}
function writeAll(obj) { localStorage.setItem(KEY, JSON.stringify(obj)); }

export function getRoundContext(sessionId) {
  return readAll()[sessionId] || null;
}
export function setRoundContext(sessionId, ctx) {
  const all = readAll();
  all[sessionId] = ctx;
  writeAll(all);
}
export function clearRoundContext(sessionId) {
  const all = readAll();
  delete all[sessionId];
  writeAll(all);
}

/** Renders the "enter round ID relayed by admin" form into a container. */
export function renderRoundContextForm(container, sessionId, onSaved) {
  container.innerHTML = `
    <div class="card">
      <p class="status-note" style="padding:0 0 10px;">
        The API doesn't yet expose the live round to teams directly (known gap —
        see backend §6.4). Enter the round ID and, if given, the deadline shown
        on your room's admin screen or QR code.
      </p>
      <div class="field">
        <label class="tier-label"><span class="primary">ラウンドID</span><span class="secondary">Round ID (this game's round UUID)</span></label>
        <input id="ctx-round-id" type="text" placeholder="uuid" />
      </div>
      <div class="field">
        <label class="tier-label"><span class="primary">締切</span><span class="secondary">Deadline (optional, ISO or leave blank)</span></label>
        <input id="ctx-deadline" type="datetime-local" />
      </div>
      <button id="ctx-save" class="cta-btn">${'確認'} / Confirm</button>
    </div>
  `;
  container.querySelector('#ctx-save').addEventListener('click', () => {
    const roundId = container.querySelector('#ctx-round-id').value.trim();
    const deadlineRaw = container.querySelector('#ctx-deadline').value;
    if (!roundId) return;
    const deadline = deadlineRaw ? new Date(deadlineRaw).toISOString() : null;
    setRoundContext(sessionId, { roundId, deadline });
    onSaved({ roundId, deadline });
  });
}
