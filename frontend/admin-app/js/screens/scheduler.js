import { api } from '../../../shared/js/api.js';
import { GAMES } from '../../../shared/js/copy.js';
import { toast } from '../../../shared/js/ui.js';

export function renderScheduler(root, navigate, role) {
  const canWrite = role === 'SUPER_ADMIN';
  root.innerHTML = `
    <div class="admin-topline"><h1 class="admin-h1">Scheduler (ops/debug)</h1></div>
    <p class="status-note" style="text-align:left;padding-left:0;">Read-only introspection of scheduled scoring/close jobs. Not part of the main admin flow.</p>
    <div id="jobs-body"><div class="spinner"></div></div>
  `;
  const body = root.querySelector('#jobs-body');

  async function load() {
    body.innerHTML = `<div class="spinner"></div>`;
    try {
      const jobs = await api.admin.scheduler.list();
      if (!jobs.length) { body.innerHTML = `<p class="status-note" style="text-align:left;padding-left:0;">No scheduled jobs.</p>`; return; }
      body.innerHTML = `
        <table class="dtable">
          <thead><tr><th>Job</th><th>Game</th><th>Round</th><th>Run at</th><th></th></tr></thead>
          <tbody>
            ${jobs.map((j) => `
              <tr>
                <td class="mono">${j.job_id.slice(0, 8)}</td>
                <td>${GAMES[j.game_code]?.en || j.game_code}</td>
                <td class="mono">${j.round_id.slice(0, 8)}</td>
                <td class="mono">${new Date(j.run_date).toLocaleString()}</td>
                <td>${canWrite ? `<button class="btn danger" data-del="${j.job_id}">Cancel</button>` : ''}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      body.querySelectorAll('[data-del]').forEach((btn) => btn.addEventListener('click', async () => {
        if (!confirm('Cancel this scheduled job?')) return;
        try { await api.admin.scheduler.remove(btn.dataset.del); toast('Cancelled'); load(); }
        catch (err) { toast(err.message, { error: true }); }
      }));
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  load();
}
