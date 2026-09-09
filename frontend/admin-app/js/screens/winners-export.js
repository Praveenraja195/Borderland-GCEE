import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';

/**
 * The Round 2 qualifier list: who goes through, and the .xlsx to forward.
 *
 * The list is read, not recomputed here — `is_qualified` is written by
 * `fn_compute_room_results` applying the round's own `qualification_rules`
 * (top N per room), so what shows up is exactly the decision the event
 * already made. The API re-runs that computation before answering, which is
 * why a score corrected two minutes ago is reflected without anyone having
 * to remember to hit "Recompute" first.
 *
 * Qualifiers are seeded across every room by total score, because that's the
 * order Round 2 needs them in — not the per-room rank they earned.
 */

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function num(value) {
  return Math.round((Number(value) || 0) * 100) / 100;
}

export function openWinnersModal(roundId, roundLabel = 'this round') {
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  backdrop.innerHTML = `<div class="modal winners-modal"><div id="winners-step"></div></div>`;
  document.body.appendChild(backdrop);

  const step = backdrop.querySelector('#winners-step');
  const close = () => backdrop.remove();
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });

  let showAll = false;
  let results = [];

  async function load() {
    step.innerHTML = `
      <h3>Round 2 Qualifiers</h3>
      <p class="import-lede">Recomputing every room's results…</p>
      <div class="spinner"></div>
    `;
    try {
      results = await api.admin.winners(roundId);
      render();
    } catch (err) {
      step.innerHTML = `
        <h3>Round 2 Qualifiers</h3>
        <p class="status-note error">${esc(err.message)}</p>
        <div class="btn-row"><button type="button" class="btn" id="close-btn">Close</button></div>
      `;
      step.querySelector('#close-btn').addEventListener('click', close);
    }
  }

  function render() {
    const qualifiers = results
      .filter((r) => r.is_qualified)
      .sort((a, b) => num(b.total_score) - num(a.total_score)
        || String(a.team_code).localeCompare(String(b.team_code)));

    const shown = showAll ? results : qualifiers;
    const roomCount = new Set(results.map((r) => r.room_code)).size;

    step.innerHTML = `
      <h3>Round 2 Qualifiers</h3>
      <p class="import-lede">
        <strong>${qualifiers.length}</strong> of ${results.length} team(s)
        across ${roomCount} room(s) qualified from ${esc(roundLabel)}.
        Who qualifies is set by each room's <em>top N</em> qualification rule —
        change it on the round page and reopen this to see the effect.
      </p>

      ${results.length === 0 ? `
        <p class="status-note">
          No results yet. Rooms produce results once their games complete
          (or after a manual recompute).
        </p>
      ` : `
        <div class="winners-toggle">
          <button type="button" class="btn tiny ${showAll ? '' : 'primary'}" id="tab-qualified">
            Qualifiers (${qualifiers.length})
          </button>
          <button type="button" class="btn tiny ${showAll ? 'primary' : ''}" id="tab-all">
            All teams (${results.length})
          </button>
        </div>

        <div class="import-table-wrap">
          <table class="dtable import-table">
            <thead>
              <tr>
                <th>${showAll ? 'Room' : 'Seed'}</th>
                <th>Team Code</th><th>Team Name</th>
                ${showAll ? '<th>Rank</th><th>Through</th>' : '<th>Room</th><th>Room Rank</th>'}
                <th>Leader</th><th>Phone</th><th>Total</th>
              </tr>
            </thead>
            <tbody>
              ${shown.map((r, i) => `
                <tr class="${!showAll || r.is_qualified ? '' : 'row-skipped'}">
                  <td class="mono">${showAll ? esc(r.room_code) : i + 1}</td>
                  <td class="mono"><strong>${esc(r.team_code)}</strong></td>
                  <td>${esc(r.team_name)}</td>
                  ${showAll
                    ? `<td class="mono">${r.rank ?? '—'}</td>
                       <td>${r.is_qualified
                            ? '<span class="pill ACTIVE">Qualified</span>'
                            : '<span class="pill NOT_STARTED">Out</span>'}</td>`
                    : `<td>${esc(r.room_code)}</td><td class="mono">${r.rank ?? '—'}</td>`}
                  <td>${esc(r.leader_name) || '<span class="muted">—</span>'}</td>
                  <td class="mono">${esc(r.leader_phone) || '<span class="muted">—</span>'}</td>
                  <td class="mono"><strong>${num(r.total_score)}</strong></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `}

      <div class="btn-row">
        <button type="button" class="btn primary" id="dl-btn" ${results.length ? '' : 'disabled'}>
          <span class="mi">download</span> Download qualifiers (.xlsx)
        </button>
        <button type="button" class="btn" id="refresh-btn"><span class="mi">refresh</span> Recompute</button>
        <button type="button" class="btn" id="close-btn">Close</button>
      </div>
    `;

    step.querySelector('#tab-qualified')?.addEventListener('click', () => { showAll = false; render(); });
    step.querySelector('#tab-all')?.addEventListener('click', () => { showAll = true; render(); });
    step.querySelector('#refresh-btn').addEventListener('click', load);
    step.querySelector('#close-btn').addEventListener('click', close);

    step.querySelector('#dl-btn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.innerHTML = `<span class="mi spin">progress_activity</span> Building…`;
      try {
        // Already recomputed by the load above — don't pay for it twice.
        const name = await api.admin.exportWinners(roundId, false);
        toast(`Downloaded ${name}`);
      } catch (err) {
        toast(err.message, { error: true });
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<span class="mi">download</span> Download qualifiers (.xlsx)`;
      }
    });
  }

  load();
}
