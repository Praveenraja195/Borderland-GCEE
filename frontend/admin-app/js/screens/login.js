// Fix §1.4: removed the editable "API Host" field. The backend now serves
// both frontends same-origin, and api.js computes DEFAULT_BASE automatically.
// The field was a phishing surface (any volunteer could accidentally point the
// admin panel at a look-alike backend) and architectural dead weight.
import { api, setToken } from '../../../shared/js/api.js';
import { HEADERS } from '../../../shared/js/copy.js';
import { toast } from '../../../shared/js/ui.js';

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <div class="bracket-header"><span class="jp">${HEADERS.adminLogin.jp}</span><span class="en">${HEADERS.adminLogin.en}</span></div>
    <div id="admin-login-form" style="margin-top:var(--gap-md);">
      <div class="field">
        <label class="tier-label"><span class="primary">ユーザー名</span><span class="secondary">Username</span></label>
        <input id="username" type="text" required autocomplete="username" />
      </div>
      <div class="field">
        <label class="tier-label"><span class="primary">パスワード</span><span class="secondary">Password</span></label>
        <input id="password" type="password" required autocomplete="current-password" />
      </div>
      <div id="err" class="field-error" style="display:none;"></div>
      <button class="cta-btn" id="login-btn" type="button">ログイン / Log In</button>
    </div>
  `;

  const errBox = root.querySelector('#err');

  async function doLogin() {
    const username = root.querySelector('#username').value.trim();
    const password = root.querySelector('#password').value;
    errBox.style.display = 'none';
    try {
      const res = await api.admin.login(username, password);
      setToken('admin', res.access_token);
      navigate('#/dashboard');
    } catch (err) {
      errBox.textContent = err.message;
      errBox.style.display = 'block';
      toast(err.message, { error: true });
    }
  }

  root.querySelector('#login-btn').addEventListener('click', doLogin);
  root.querySelector('#password').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') doLogin();
  });
}
