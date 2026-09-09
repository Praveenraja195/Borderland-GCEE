import { api } from '../../../shared/js/api.js';
import { toast } from '../../../shared/js/ui.js';

export function renderAdminAccounts(root, navigate) {
  root.innerHTML = `
    <div class="admin-topline">
      <h1 class="admin-h1">Admin Accounts</h1>
      <button id="new-admin" class="btn primary"><span class="mi">person_add</span> New Admin</button>
    </div>
    <div id="admins-body"><div class="spinner"></div></div>
  `;
  const body = root.querySelector('#admins-body');

  async function load() {
    body.innerHTML = `<div class="spinner"></div>`;
    try {
      const admins = await api.admin.admins.list();
      body.innerHTML = `
        <table class="dtable">
          <thead><tr><th>Username</th><th>Role</th><th></th></tr></thead>
          <tbody>
            ${admins.map((a) => `
              <tr>
                <td class="mono">${a.username}</td>
                <td><span class="pill NOT_STARTED">${a.role}</span></td>
                <td><div class="btn-row">
                  <button class="btn" data-pw="${a.admin_id}"><span class="mi">key</span> Reset Password</button>
                  <button class="btn danger" data-del="${a.admin_id}"><span class="mi">block</span> Deactivate</button>
                </div></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
      body.querySelectorAll('[data-pw]').forEach((btn) => btn.addEventListener('click', async () => {
        const pw = prompt('New password:');
        if (!pw) return;
        try { await api.admin.admins.setPassword(btn.dataset.pw, pw); toast('Password updated'); }
        catch (err) { toast(err.message, { error: true }); }
      }));
      body.querySelectorAll('[data-del]').forEach((btn) => btn.addEventListener('click', async () => {
        if (!confirm('Deactivate this admin account? (You cannot deactivate yourself.)')) return;
        try { await api.admin.admins.remove(btn.dataset.del); toast('Deactivated'); load(); }
        catch (err) { toast(err.message, { error: true }); }
      }));
    } catch (err) {
      body.innerHTML = `<p class="status-note error">${err.message}</p>`;
    }
  }

  root.querySelector('#new-admin').addEventListener('click', () => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h3>New admin</h3>
        <form id="create-admin-form">
          <div class="field"><label class="tier-label"><span class="primary">ユーザー名</span><span class="secondary">Username</span></label><input name="username" required /></div>
          <div class="field"><label class="tier-label"><span class="primary">パスワード</span><span class="secondary">Password</span></label><input name="password" type="password" required /></div>
          <div class="field">
            <label class="tier-label"><span class="primary">役割</span><span class="secondary">Role</span></label>
            <select name="role">
              <option value="ROOM_ADMIN">ROOM_ADMIN</option>
              <option value="SUPER_ADMIN">SUPER_ADMIN</option>
            </select>
          </div>
          <div class="btn-row">
            <button type="submit" class="btn primary">Create</button>
            <button type="button" class="btn" id="cancel">Cancel</button>
          </div>
        </form>
      </div>
    `;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#cancel').addEventListener('click', () => backdrop.remove());
    backdrop.querySelector('#create-admin-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        await api.admin.admins.create(fd.get('username'), fd.get('password'), fd.get('role'));
        backdrop.remove();
        toast('Admin created');
        load();
      } catch (err) { toast(err.message, { error: true }); }
    });
  });

  load();
}
