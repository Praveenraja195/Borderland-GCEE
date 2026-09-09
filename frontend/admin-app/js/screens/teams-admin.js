import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';
import { openTeamImportModal } from './team-import.js';

export function renderTeamsAdmin(root, navigate, role) {
  const canWrite = role === 'SUPER_ADMIN';
  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Teams</h1>
      ${canWrite ? `
        <div class="btn-row">
          <button id="import-teams" class="btn primary"><span class="mi">upload_file</span> Import from Sheet</button>
          <button id="new-team" class="btn"><span class="mi">person_add</span> New Team</button>
        </div>
      ` : ''}
    </div>
    <div id="teams-body"><div class="spinner"></div></div>
  `;

  const body = root.querySelector('#teams-body');

  async function load() {
    body.innerHTML = `<div class="spinner"></div>`;
    try {
      const teams = await api.admin.teams.list();
      if (!teams.length) {
        body.innerHTML = `
          <div class="empty-state">
            <div class="empty-icon"><span class="mi">group</span></div>
            No teams registered yet.
            ${canWrite ? 'Import your registration sheet to create them all at once.' : ''}
          </div>
        `;
        return;
      }
      body.innerHTML = `
        <div class="dash-card">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <span style="font-size:0.8rem;color:#64748b;">${teams.length} teams registered (max 40)</span>
          </div>
          <table class="dtable">
            <thead><tr><th>Code</th><th>Name</th><th>Leader</th><th>Phone</th><th>Room</th><th>Suit</th><th>Status</th>${canWrite ? '<th>Actions</th>' : ''}</tr></thead>
            <tbody>
              ${teams.map(t => `
                <tr>
                  <td class="mono"><strong>${t.team_code}</strong></td>
                  <td>${t.team_name}</td>
                  <td>${t.leader_name || '<span style="color:#94a3b8;">—</span>'}</td>
                  <td class="mono">${t.leader_phone || '<span style="color:#94a3b8;">—</span>'}</td>
                  <td>${t.room_code ? `<span class="pill ACTIVE">${t.room_code}</span>` : '<span style="color:#94a3b8;">—</span>'}</td>
                  <td>${t.suit_code || '<span style="color:#94a3b8;">—</span>'}</td>
                  <td>${t.has_selected ? '<span class="pill IN_PROGRESS">Selected</span>' : '<span class="pill NOT_STARTED">Not selected</span>'}</td>
                  ${canWrite ? `
                    <td>
                      <div class="btn-row">
                        <button class="btn" data-pw="${t.team_id}"><span class="mi">key</span> Reset PW</button>
                        <button class="btn danger" data-del="${t.team_id}" data-code="${t.team_code}"><span class="mi">delete</span> Delete</button>
                      </div>
                    </td>
                  ` : ''}
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
      if (canWrite) {
        body.querySelectorAll('[data-pw]').forEach(btn => btn.addEventListener('click', async () => {
          const pw = prompt('New password for this team:');
          if (!pw) return;
          try { await api.admin.teams.setPassword(btn.dataset.pw, pw); toast('Password updated'); }
          catch (err) { toast(err.message, { error: true }); }
        }));
        body.querySelectorAll('[data-del]').forEach(btn => btn.addEventListener('click', async () => {
          if (!confirm(`Delete team ${btn.dataset.code}? This cannot be undone if the round is active.`)) return;
          try { await api.admin.teams.remove(btn.dataset.del); toast('Team deleted'); load(); }
          catch (err) { toast(err.message, { error: true }); }
        }));
      }
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  if (canWrite) {
    root.querySelector('#import-teams').addEventListener('click', () => {
      openTeamImportModal(load);
    });

    root.querySelector('#new-team').addEventListener('click', () => {
      const backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop';
      backdrop.innerHTML = `
        <div class="modal">
          <h3>Create New Team</h3>
          <form id="create-team-form">
            <div class="field">
              <label class="tier-label"><span class="primary">Team Code</span><span class="secondary">Unique identifier (e.g. T01)</span></label>
              <input name="team_code" required placeholder="e.g. T01" />
            </div>
            <div class="field">
              <label class="tier-label"><span class="primary">Team Name</span><span class="secondary">Display name</span></label>
              <input name="team_name" required placeholder="e.g. Dragon Warriors" />
            </div>
            <div class="field">
              <label class="tier-label"><span class="primary">Password</span><span class="secondary">Login password for the team</span></label>
              <input name="password" type="password" required />
            </div>
            <div class="btn-row">
              <button type="submit" class="btn primary">Create Team</button>
              <button type="button" class="btn" id="cancel">Cancel</button>
            </div>
          </form>
        </div>
      `;
      document.body.appendChild(backdrop);
      backdrop.querySelector('#cancel').addEventListener('click', () => backdrop.remove());
      backdrop.querySelector('#create-team-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(e.target);
        try {
          await api.admin.teams.create(fd.get('team_code'), fd.get('team_name'), fd.get('password'));
          backdrop.remove();
          toast('Team created');
          load();
        } catch (err) { toast(err.message, { error: true }); }
      });
    });
  }

  load();
}
