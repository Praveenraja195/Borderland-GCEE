import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';

export function renderRoundsOverview(root, navigate) {
  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Rounds</h1>
      <button id="new-round" class="btn primary">+ New round</button>
    </div>
    <div id="rounds-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#rounds-body');

  async function load() {
    body.innerHTML = `<div class="spinner"></div>`;
    try {
      const rounds = await api.admin.listRounds();
      if (!rounds.length) { body.innerHTML = `<p class="status-note">No rounds yet — create one to get started.</p>`; return; }
      body.innerHTML = `
        <table class="dtable">
          <thead><tr><th>#</th><th>Name</th><th>Status</th><th></th></tr></thead>
          <tbody>
            ${rounds.map((r) => `
              <tr>
                <td>${r.round_number}</td>
                <td>${r.name}</td>
                <td><span class="pill ${r.status}">${r.status?.replace('_',' ')}</span></td>
                <td><a class="rowlink" href="#/rounds/${r.round_id}">Open →</a></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  root.querySelector('#new-round').addEventListener('click', () => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3>New round</h3>
        <form id="create-round-form">
          <div class="field"><label class="tier-label"><span class="primary">ラウンド名</span><span class="secondary">Round Name</span></label><input name="name" required /></div>
          <div class="field"><label class="tier-label"><span class="primary">番号</span><span class="secondary">Round Number</span></label><input name="round_number" type="number" min="1" required /></div>
          <div class="btn-row">
            <button type="submit" class="btn primary">Create</button>
            <button type="button" class="btn" id="cancel-modal">Cancel</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#cancel-modal').addEventListener('click', () => backdrop.remove());
    backdrop.querySelector('#create-round-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        const round = await api.admin.createRound(Number(fd.get('round_number')), fd.get('name'));
        backdrop.remove();
        toast('Round created — 10 rooms seeded (R01–R10)');
        navigate(`#/rounds/${round.round_id}`);
      } catch (err) {
        toast(err.message, { error: true });
      }
    });
  });

  load();
}
