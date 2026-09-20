import { api, setToken } from '../../../shared/js/api.js';
import { enterFullscreen, isFullscreenSupported, isIOS, isStandalone } from '../fullscreen.js';
import { HEADERS, FIELDS, BUTTONS, tierLabelHTML, translateError } from '../../../shared/js/copy.js';
import { toast, friendlyError } from '../../../shared/js/ui.js';
import { suitIconSVG } from '../../../shared/js/suit-icons.js';

export function renderLogin(root, navigate) {
  root.innerHTML = `
    <div class="bl-login-header-section">
      <div class="bl-login-logo-container">
        <img src="../shared/img/borderland_logo.png" alt="Borderland @ GCEE" class="bl-login-logo" />
      </div>
      <div class="bracket-header" style="padding-top: 6px; padding-bottom: 2px;">
        <span class="jp">${HEADERS.teamLogin.jp}</span>
        <span class="en">${HEADERS.teamLogin.en}</span>
      </div>
    </div>

    <div class="scroll-area">
      <form id="login-form">
        <div class="field">
          <label class="tier-label">${tierLabelHTML(FIELDS.teamCode)}</label>
          <input name="team_code" type="text" autocomplete="off" placeholder="e.g. B@GCEE-1234#" required />
        </div>
        <div class="field">
          <label class="tier-label">${tierLabelHTML(FIELDS.password)}</label>
          <input name="password" type="password" autocomplete="current-password" placeholder="First 4 digits of your phone number" required />
        </div>
        <div id="err" class="field-error" style="display:none;"></div>
      </form>
      ${isIOS() && !isStandalone() ? `
        <p class="fs-hint">
          iPhone: for full screen, tap <strong>Share</strong> → <strong>Add to Home Screen</strong> and open the app from there.
        </p>` : ''}
    </div>

    <div class="cta-dock">
      <button id="submit-btn" form="login-form" class="cta-btn" type="submit">
        ${BUTTONS.login.jp} / ${BUTTONS.login.en}
      </button>
    </div>
  `;

  const form = root.querySelector('#login-form');
  const errBox = root.querySelector('#err');
  const btn = root.querySelector('#submit-btn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    // Full screen must be requested from the gesture itself, so do it before
    // the login round trip; it simply stays on if the password was wrong.
    if (isFullscreenSupported()) enterFullscreen();
    errBox.style.display = 'none';
    const fd = new FormData(form);
    const team_code = fd.get('team_code').trim();
    const password = fd.get('password');
    btn.disabled = true;
    btn.textContent = '…';
    try {
      const res = await api.team.login(team_code, password);
      setToken('team', res.access_token);
      localStorage.setItem('bl_team_code', team_code);
      navigate('#/selection');
    } catch (err) {
      errBox.textContent = friendlyError(err, translateError);
      errBox.style.display = 'block';
      toast(err.message, { error: true });
    } finally {
      btn.disabled = false;
      btn.textContent = `${BUTTONS.login.jp} / ${BUTTONS.login.en}`;
    }
  });
}
